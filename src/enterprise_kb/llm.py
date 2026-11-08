"""LiteLLM 封装：统一走 API，primary → fallback 自动降级。

返回结构化结果（含 token 用量），为 Phase 3 成本追踪打基础。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import litellm

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResult:
    """一次 LLM 调用的结果（含用量 + 成本，供可观测/成本追踪）。"""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    input_cost: float = 0.0  # 输入成本（美元）
    output_cost: float = 0.0  # 输出成本（美元）

    @property
    def cost(self) -> float:
        """总成本（美元）。"""
        return self.input_cost + self.output_cost


def _setup_keys() -> None:
    """把已配置的 API key 注入 litellm（SecretStr → 明文）。

    除了设置 litellm.<provider>_key 属性，还显式写入对应环境变量——
    因为 litellm 的 deepseek provider 只读 DEEPSEEK_API_KEY 环境变量
    （get_secret_str），不读 litellm.deepseek_key 属性，也不读 ChatLiteLLM
    的 api_key 字段；若不写环境变量，长时间运行的 streamlit 进程会间歇性
    读不到 key → 401 governor。
    """
    settings = get_settings()
    if settings.anthropic_api_key:
        litellm.anthropic_key = settings.anthropic_api_key.get_secret_value()
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key.get_secret_value()
    if settings.deepseek_api_key:
        litellm.deepseek_key = settings.deepseek_api_key.get_secret_value()
        os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key.get_secret_value()
    # 自动丢弃 provider 不支持的参数（如 claude 不支持 temperature=0.0），避免 fallback 因参数报错
    litellm.drop_params = True


def _is_retryable(e: Exception) -> bool:
    """判断是否为可重试的限流/临时错误（governor / rate limit / 超时）。"""
    msg = str(e).lower()
    return any(
        k in msg
        for k in ("governor", "rate limit", "rate_limit", "429", "timeout", "overloaded", "temporarily")
    )


def _mask(key: str | None) -> str:
    """把 key 脱敏成 sk-xxx…yyy 形式，便于日志诊断。"""
    if not key:
        return "None"
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "(short)"


def _deepseek_key() -> str | None:
    """返回 deepseek key 明文（未配置则 None）。"""
    settings = get_settings()
    if settings.deepseek_api_key:
        return settings.deepseek_api_key.get_secret_value()
    return None


# governor 短时窗口（约 3s），退避重试可熬过窗口
_RETRY_BACKOFF = [2.0, 4.0]


def generate(messages: list[dict], model: str | None = None) -> LLMResult:
    """生成文本。默认 primary，失败自动降级 fallback。

    Args:
        messages: OpenAI 格式 messages 列表。
        model: 显式指定模型（可选，None 时走 primary→fallback）。

    Raises:
        RuntimeError: 所有候选模型均调用失败。
    """
    _setup_keys()
    settings = get_settings()
    candidates = [model] if model else [settings.llm.primary, settings.llm.fallback]
    # 显式传 key，绕过 litellm 全局状态（长时间运行的多线程进程可能污染它）
    ds_key = _deepseek_key()
    logger.info("generate() 显式 key=%s（全局 litellm.deepseek_key=%s）", _mask(ds_key), _mask(getattr(litellm, "deepseek_key", None)))

    last_err: Exception | None = None
    for m in candidates:
        for attempt in range(len(_RETRY_BACKOFF) + 1):  # 1 次初次 + 2 次重试
            try:
                resp = litellm.completion(
                    model=m,
                    messages=messages,
                    temperature=settings.llm.temperature,
                    api_key=ds_key,
                )
                usage = getattr(resp, "usage", None)
                result = LLMResult(
                    content=resp.choices[0].message.content or "",
                    model=m,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                )
                # 用 litellm cost map 算成本（token × 单价，input/output 分开）；失败则置 0，不影响主流程
                try:
                    info = litellm.get_model_info(m)
                    result.input_cost = float(info.get("input_cost_per_token", 0) or 0) * result.prompt_tokens
                    result.output_cost = float(info.get("output_cost_per_token", 0) or 0) * result.completion_tokens
                except Exception as e:  # noqa: BLE001
                    logger.debug("成本计算失败 model=%s err=%s", m, e)
                logger.debug("LLM 调用成功 model=%s tokens=%s cost=%s", m, result.completion_tokens, result.cost)
                return result
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < len(_RETRY_BACKOFF) and _is_retryable(e):
                    delay = _RETRY_BACKOFF[attempt]
                    logger.warning(
                        "LLM 限流/临时错误，%.0fs 后重试（%d/%d）model=%s",
                        delay,
                        attempt + 1,
                        len(_RETRY_BACKOFF),
                        m,
                    )
                    time.sleep(delay)
                    continue
                logger.warning("LLM 调用失败 model=%s err=%s，尝试下一个", m, e)
                break

    raise RuntimeError(f"所有 LLM 模型调用失败: {last_err}")

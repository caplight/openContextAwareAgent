"""LiteLLM 封装：统一走 API，primary → fallback 自动降级。

返回结构化结果（含 token 用量），为 Phase 3 成本追踪打基础。
"""

from __future__ import annotations

from dataclasses import dataclass

import litellm

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResult:
    """一次 LLM 调用的结果（含用量，供可观测/成本追踪）。"""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _setup_keys() -> None:
    """把已配置的 API key 注入 litellm（SecretStr → 明文）。"""
    settings = get_settings()
    if settings.anthropic_api_key:
        litellm.anthropic_key = settings.anthropic_api_key.get_secret_value()
    if settings.deepseek_api_key:
        litellm.deepseek_key = settings.deepseek_api_key.get_secret_value()


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

    last_err: Exception | None = None
    for m in candidates:
        try:
            resp = litellm.completion(
                model=m,
                messages=messages,
                temperature=settings.llm.temperature,
            )
            usage = getattr(resp, "usage", None)
            result = LLMResult(
                content=resp.choices[0].message.content or "",
                model=m,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
            logger.debug("LLM 调用成功 model=%s tokens=%s", m, result.completion_tokens)
            return result
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("LLM 调用失败 model=%s err=%s，尝试下一个", m, e)

    raise RuntimeError(f"所有 LLM 模型调用失败: {last_err}")

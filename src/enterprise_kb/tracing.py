"""可观测：Langfuse v4 SDK 封装（未启用时静默 no-op）。

Langfuse v4 SDK（OpenTelemetry 底层）用 `start_as_current_observation` 创建 span，
延迟由 span 的 start/end 自动记录；token 用量 / 成本经 `usage_details` / `cost_details` 传入。

用法（graph 节点内）：
    with trace("retrieve", as_type="retriever", input={...}) as span:
        ...
        if span is not None:
            span.update(output={...}, usage_details={...})
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

_client = None


def get_client():
    """懒加载 v4 Langfuse client（未启用返回 None）。"""
    global _client
    settings = get_settings()
    if not settings.langfuse.enabled:
        return None
    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse.public_key,
            secret_key=settings.langfuse.secret_key,
            host=settings.langfuse.host,
        )
        logger.info("Langfuse client 已初始化（host=%s）", settings.langfuse.host)
    return _client


@contextmanager
def trace(name: str, as_type: str = "span", **kwargs: Any) -> Iterator:
    """创建（或包裹）一个 Langfuse observation span。

    - 未启用（LANGFUSE__ENABLED=false）或发送失败时 yield None，静默跳过，不影响主流程。
    - 延迟由 span 自动记录；token/成本经 span.update(usage_details=..., cost_details=...) 补充。

    Args:
        name: span 名称（如 retrieve / rerank / generate）。
        as_type: span 类型（span / generation / retriever / chain / agent / tool / evaluator）。
        **kwargs: 透传给 start_as_current_observation（input / output / model / metadata 等）。
    """
    client = get_client()
    if client is None:
        yield None
        return
    try:
        with client.start_as_current_observation(name=name, as_type=as_type, **kwargs) as span:
            yield span
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse trace 失败（不影响主流程）: %s", e)
        yield None


def flush() -> None:
    """刷出待发送的 trace（脚本 / 进程结束前调用）。"""
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception as e:  # noqa: BLE001
            logger.warning("Langfuse flush 失败: %s", e)

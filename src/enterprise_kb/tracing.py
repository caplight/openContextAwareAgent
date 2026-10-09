"""可观测（M1.7）：Langfuse trace 轻量封装，Phase 1 即接入（边做功能边 trace）。

未启用（LANGFUSE__ENABLED=false）时静默跳过，不影响主流程。
"""

from __future__ import annotations

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

_client = None


def get_client():
    """懒加载 Langfuse client（未启用返回 None）。"""
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
    return _client


def trace_query(query: str, contexts: list[str], answer: str, model: str | None = None) -> None:
    """记录一次查询链路（retrieve → generate）。"""
    client = get_client()
    if client is None:
        return
    try:
        trace = client.trace(name="rag-query", input={"query": query})
        trace.span(name="retrieve", input={"query": query}, output={"contexts": contexts})
        trace.span(
            name="generate", input={"contexts": contexts}, output={"answer": answer, "model": model}
        )
        trace.update(output={"answer": answer, "model": model})
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse trace 失败（不影响主流程）: %s", e)

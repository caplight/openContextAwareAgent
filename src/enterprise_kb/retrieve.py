"""检索（M1.3）：纯向量 top-k（Phase 1 先不做混合检索 / rerank）。"""

from __future__ import annotations

from enterprise_kb.config import get_settings
from enterprise_kb.embed import encode, get_client


def retrieve(query: str, top_k: int | None = None) -> list[str]:
    """检索最相关的 top-k 个 chunk 文本。"""
    settings = get_settings()
    top_k = top_k or settings.retrieval.top_k
    client = get_client()

    query_vec = encode([query])[0]
    hits = client.query_points(
        collection_name=settings.qdrant.collection,
        query=query_vec,
        limit=top_k,
    )
    return [h.payload["text"] for h in hits.points]

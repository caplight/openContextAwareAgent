"""检索（M1.3 / Phase 2a）：支持纯向量（naive）与混合检索（BM25 + dense + RRF）。"""

from __future__ import annotations

from enterprise_kb.config import get_settings
from enterprise_kb.embed import encode, get_client
from enterprise_kb.hybrid import BM25Retriever, rrf_fusion
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

# 全局 BM25 索引（惰性初始化，从 Qdrant 读全部 chunk text 构建）
_bm25: BM25Retriever | None = None

# dense 检索时取多少候选参与 RRF 融合（比最终 top_k 更大，给 BM25 留融合空间）
_FUSION_CANDIDATE_FACTOR = 4


def retrieve(query: str, top_k: int | None = None) -> list[str]:
    """Phase 1 naive：纯 dense 向量 top-k。"""
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


def _get_bm25() -> BM25Retriever:
    """惰性构建全局 BM25 索引（首次调用时从 Qdrant scroll 全部 chunk text）。"""
    global _bm25
    if _bm25 is None:
        settings = get_settings()
        client = get_client()
        points, _ = client.scroll(
            collection_name=settings.qdrant.collection,
            limit=10_000,
            with_payload=True,
            with_vectors=False,
        )
        texts = [p.payload["text"] for p in points]
        _bm25 = BM25Retriever(texts)
        logger.info("全局 BM25 索引已构建（%d chunks）", len(texts))
    return _bm25


def _dense_ranked(query: str, top_n: int) -> list[str]:
    """dense 向量检索，返回 top-n 文档（按相关度降序）。"""
    settings = get_settings()
    client = get_client()
    query_vec = encode([query])[0]
    hits = client.query_points(
        collection_name=settings.qdrant.collection,
        query=query_vec,
        limit=top_n,
    )
    return [h.payload["text"] for h in hits.points]


def retrieve_hybrid(query: str, top_k: int | None = None) -> list[str]:
    """Phase 2a 混合检索：dense（Qdrant）+ sparse（BM25）+ RRF 融合。"""
    settings = get_settings()
    top_k = top_k or settings.retrieval.top_k
    candidate_n = top_k * _FUSION_CANDIDATE_FACTOR

    dense_ranked = _dense_ranked(query, candidate_n)
    bm25 = _get_bm25()
    sparse_ranked = bm25.search(query, k=candidate_n)

    fused = rrf_fusion([dense_ranked, sparse_ranked])
    return fused[:top_k]

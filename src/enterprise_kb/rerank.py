"""Phase 2b：Reranker 精排（bge-reranker-v2-m3，cross-encoder）。

混合检索（dense + BM25 + RRF）先取 top-n 候选，再用 reranker 对候选做
query-doc 成对相关性打分，精排到 top-k。cross-encoder 比 bi-encoder（dense）
更精确，能弥补「召回相关性不够准」的短板。
"""

from __future__ import annotations

from sentence_transformers import CrossEncoder

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

# 模块级缓存（bge-reranker-v2-m3 约 2.2GB）
_reranker: CrossEncoder | None = None


def get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        settings = get_settings()
        logger.info("加载 reranker 模型 %s", settings.reranker.model)
        _reranker = CrossEncoder(settings.reranker.model)
    return _reranker


def rerank(query: str, candidates: list[str], top_k: int) -> list[str]:
    """对候选精排，返回最相关的 top-k（保持原顺序的稳定排序）。"""
    if not candidates:
        return []
    model = get_reranker()
    pairs = [(query, c) for c in candidates]
    scores = model.predict(pairs)  # 批量打分，scores 是 numpy 数组
    # 按分数降序，分数相同保持原顺序（stable）
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [c for c, _ in ranked[:top_k]]

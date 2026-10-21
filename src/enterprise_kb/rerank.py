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


def rerank_batch(
    queries: list[str],
    candidates_list: list[list[str]],
    top_k: int,
    batch_size: int = 32,
) -> list[list[str]]:
    """批量精排多个 query 的候选，一次 cross-encoder 前向搞定，比逐条 rerank 快数倍。

    CPU 上 cross-encoder 逐条 query 串行（每条一次 predict）开销大；把所有
    query-candidate pairs 合并成一个大 batch 一次 predict，减少 Python→C++
    调用次数 + 大 batch 更好的向量化，显著提速。

    返回与 queries 等长的 list[list[str]]，每个是精排后的 top-k。
    """
    if not queries:
        return []
    model = get_reranker()
    pairs: list[tuple[str, str]] = []
    counts: list[int] = []
    for q, cands in zip(queries, candidates_list):
        pairs.extend((q, c) for c in cands)
        counts.append(len(cands))
    if not pairs:
        return [[] for _ in queries]
    scores = model.predict(pairs, batch_size=batch_size)  # 一次大 batch 前向
    results: list[list[str]] = []
    idx = 0
    for i, n in enumerate(counts):
        # 每个 query 的候选分数切片，按分数降序（stable，同分保持原顺序）
        seg = list(zip(candidates_list[i], scores[idx : idx + n]))
        seg.sort(key=lambda x: x[1], reverse=True)
        results.append([c for c, _ in seg[:top_k]])
        idx += n
    return results

"""混合检索（Phase 2a）：dense（bge-m3 语义）+ sparse（BM25 关键词）+ RRF 融合。

设计原则：
- BM25 用 bm25s（轻量、纯 numpy，843 chunks 内存索引无压力）
- dense 复用现有 bge-m3（Qdrant 或内存相似度，由调用方传入）
- RRF（Reciprocal Rank Fusion）只依赖排名不比较原始分数，解决 dense/sparse 分数不可比问题
"""

from __future__ import annotations

import bm25s

from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

# RRF 常数（k=60 是业界常用默认）
RRF_K = 60


class BM25Retriever:
    """封装 bm25s 的稀疏（关键词）检索。

    corpus 为文档字符串列表；内部 tokenize + 建 BM25 索引。
    """

    def __init__(self, corpus: list[str]) -> None:
        self._corpus = corpus
        self._retriever = bm25s.BM25(corpus=corpus)
        tokens = bm25s.tokenize(corpus, stopwords="en", show_progress=False)
        self._retriever.index(tokens, show_progress=False)
        logger.info("BM25 索引已建立，corpus=%d", len(corpus))

    def search(self, query: str, k: int) -> list[str]:
        """返回 BM25 排序后的 top-k 文档（字符串，按相关度降序）。"""
        if not self._corpus:
            return []
        query_tokens = bm25s.tokenize(query, stopwords="en", show_progress=False)
        results, _scores = self._retriever.retrieve(query_tokens, k=k, show_progress=False)
        # results 是 numpy 数组 shape (1, k)，results[0] 是文档列表
        if results.shape[0] == 0:
            return []
        return [str(doc) for doc in results[0]]


def rrf_fusion(ranked_lists: list[list[str]], k: int = RRF_K) -> list[str]:
    """RRF 融合多个「按相关度降序」的文档列表，返回融合后的排序。

    score(d) = Σ_i 1 / (k + rank_i(d))
    rank 从 1 开始（rank=1 是最相关的第一个）。

    Args:
        ranked_lists: 每个检索器的排序结果（文档字符串，最相关在前）。
        k: RRF 常数（默认 60）。

    Returns:
        融合后按 RRF 分数降序的文档列表（无重复）。
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked, start=1):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    # 按分数降序，分数相同则按首次出现顺序稳定排序
    return sorted(scores, key=lambda d: scores[d], reverse=True)


def hybrid_retrieve(
    query: str,
    dense_ranked: list[str],
    bm25: BM25Retriever,
    top_k: int,
    sparse_k: int | None = None,
) -> list[str]:
    """混合检索：dense（调用方算好）+ sparse（BM25）+ RRF 融合。

    Args:
        query: 用户查询。
        dense_ranked: dense 检索的排序结果（最相关在前）。
        bm25: 预构建的 BM25 索引（corpus 与 dense_ranked 同源）。
        top_k: 最终返回条数。
        sparse_k: BM25 取 top 几参与融合（None 则取全部，通常与 dense 同规模即可）。

    Returns:
        融合后的 top-k 文档列表。
    """
    sparse_k = sparse_k or len(bm25._corpus)
    sparse_ranked = bm25.search(query, k=sparse_k)
    fused = rrf_fusion([dense_ranked, sparse_ranked])
    return fused[:top_k]

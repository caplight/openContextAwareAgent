"""框架无关的知识库检索核心逻辑。

复用 Phase 2 的检索链路（retrieve_hybrid_candidates + rerank），
返回最相关片段（结构化 SearchResult，不生成答案，方案 A：检索与生成分离）。
"""

from __future__ import annotations

from enterprise_kb.core.result import SearchHit, SearchResult

# 知识库为空时的提示（由调用方在 to_text 时传入）
_EMPTY_KB_HINT = "[提示] 知识库为空或未建索引（先运行 `kb ingest` 摄入文档）。"


def kb_search(query: str, top_k: int = 5) -> SearchResult:
    """检索企业知识库文档（K8s / AWS 等官方文档语料）。

    用于回答「怎么做 / 最佳实践是什么」这类知识性问题（如「OOM 了怎么调 limits」）。
    返回结构化 SearchResult（最相关片段，带编号），供后续综合判断；不生成最终答案。

    Args:
        query: 检索查询（自然语言问题或关键词）
        top_k: 返回片段数，默认 5
    """
    from enterprise_kb.rerank import rerank
    from enterprise_kb.retrieve import retrieve_hybrid_candidates

    candidates = retrieve_hybrid_candidates(query)
    contexts = rerank(query, candidates, top_k)
    hits = [SearchHit(snippet=ctx) for ctx in contexts]
    return SearchResult(query=query, hits=hits, note=_EMPTY_KB_HINT)

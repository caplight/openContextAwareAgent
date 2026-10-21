"""LangGraph 编排：把 RAG 流程画成状态图（retrieve → rerank → generate）。

Phase 2b 起采用「混合召回 → rerank 精排 → 生成」三段式：
- retrieve：dense（bge-m3）+ sparse（BM25）+ RRF 融合，产出候选池
- rerank：bge-reranker-v2-m3 cross-encoder 精排到 top-k
- generate：RAG prompt + LLM 生成，带 token 用量

每个节点用 `trace()` 埋 Langfuse span（延迟自动记录、token/成本可回填），
状态图的价值在这里体现（节点可插拔、可并行、可回溯、可观测）。
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from enterprise_kb.config import get_settings
from enterprise_kb.generate import generate_answer
from enterprise_kb.rerank import rerank
from enterprise_kb.retrieve import retrieve_hybrid_candidates
from enterprise_kb.tracing import flush, trace


class RAGState(TypedDict, total=False):
    query: str
    candidates: list[str]  # hybrid 召回候选池（rerank 前）
    contexts: list[str]    # rerank 精排后的 top-k
    answer: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float


def retrieve_node(state: RAGState) -> dict:
    query = state["query"]
    with trace("retrieve", as_type="retriever", input={"query": query}) as span:
        candidates = retrieve_hybrid_candidates(query)
        if span is not None:
            span.update(output={"candidate_count": len(candidates)})
        return {"candidates": candidates}


def rerank_node(state: RAGState) -> dict:
    settings = get_settings()
    with trace("rerank", as_type="span", input={"candidate_count": len(state["candidates"])}) as span:
        contexts = rerank(state["query"], state["candidates"], settings.retrieval.top_k)
        if span is not None:
            span.update(output={"context_count": len(contexts)})
        return {"contexts": contexts}


def generate_node(state: RAGState) -> dict:
    with trace("generate", as_type="generation", input={"context_count": len(state["contexts"])}) as span:
        result = generate_answer(state["query"], state["contexts"])
        if span is not None:
            span.update(
                output={"answer": result.content},
                model=result.model,
                usage_details={"input": result.prompt_tokens, "output": result.completion_tokens},
                cost_details={"input": result.input_cost, "output": result.output_cost, "total": result.cost},
            )
        return {
            "answer": result.content,
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "cost": result.cost,
        }


def build_graph():
    g = StateGraph(RAGState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("rerank", rerank_node)
    g.add_node("generate", generate_node)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_edge("rerank", "generate")
    g.add_edge("generate", END)
    return g.compile()


# 模块级编译好的 graph（供 API 调用）
rag_graph = build_graph()


def ask(query: str) -> dict:
    """对外统一入口：输入 query，返回完整状态（contexts/answer/model/tokens）。

    整个链路包在一个 `rag-query` root trace 下，节点 span 为其子级。
    """
    with trace("rag-query", as_type="chain", input={"query": query}) as root:
        result = rag_graph.invoke({"query": query})
        if root is not None:
            root.update(output={"answer": result.get("answer"), "model": result.get("model")})
        return result

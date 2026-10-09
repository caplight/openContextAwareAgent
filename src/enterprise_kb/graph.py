"""LangGraph 编排：把 RAG 流程画成状态图（retrieve → generate）。

Phase 1 只有两个节点；Phase 2/3 会加入 rerank、路由、降级等节点，
状态图的价值在这里体现（节点可插拔、可并行、可回溯）。
"""

from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from enterprise_kb.generate import generate_answer
from enterprise_kb.retrieve import retrieve


class RAGState(TypedDict, total=False):
    query: str
    contexts: list[str]
    answer: str
    model: str
    prompt_tokens: int
    completion_tokens: int


def retrieve_node(state: RAGState) -> dict:
    return {"contexts": retrieve(state["query"])}


def generate_node(state: RAGState) -> dict:
    result = generate_answer(state["query"], state["contexts"])
    return {
        "answer": result.content,
        "model": result.model,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
    }


def build_graph():
    g = StateGraph(RAGState)
    g.add_node("retrieve", retrieve_node)
    g.add_node("generate", generate_node)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


# 模块级编译好的 graph（供 API 调用）
rag_graph = build_graph()


def ask(query: str) -> dict:
    """对外统一入口：输入 query，返回完整状态（contexts/answer/model/tokens）。"""
    return rag_graph.invoke({"query": query})

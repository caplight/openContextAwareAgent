"""生成（M1.4）：RAG prompt + LLM 生成答案（引用 retrieved chunks）。"""

from __future__ import annotations

from enterprise_kb.llm import LLMResult
from enterprise_kb.llm import generate as _llm_generate

_SYSTEM_PROMPT = (
    "You are a helpful enterprise knowledge-base assistant. "
    "Answer the user's question using ONLY the provided context chunks. "
    "If the context does not contain the answer, say so honestly instead of guessing. "
    "Cite the relevant context where helpful."
)


def build_prompt(query: str, contexts: list[str]) -> list[dict]:
    """构造 RAG messages（system + 拼接 context + user query）。"""
    ctx_block = "\n\n---\n\n".join(f"[{i + 1}] {ctx}" for i, ctx in enumerate(contexts))
    user = f"Context:\n{ctx_block}\n\nQuestion: {query}\n\nAnswer:"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def generate_answer(query: str, contexts: list[str], model: str | None = None) -> LLMResult:
    """生成最终答案。"""
    messages = build_prompt(query, contexts)
    return _llm_generate(messages, model=model)

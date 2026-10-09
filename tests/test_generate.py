"""生成层测试：RAG prompt 结构。"""

from __future__ import annotations

from enterprise_kb.generate import build_prompt


def test_build_prompt_structure():
    msgs = build_prompt("How to scale?", ["ctx one", "ctx two"])
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    # 所有 context 和 query 都拼进 user message
    assert "[1] ctx one" in msgs[1]["content"]
    assert "[2] ctx two" in msgs[1]["content"]
    assert "How to scale?" in msgs[1]["content"]


def test_build_prompt_empty_contexts():
    msgs = build_prompt("Q", [])
    assert msgs[1]["role"] == "user"
    assert "Context:\n\n" in msgs[1]["content"]

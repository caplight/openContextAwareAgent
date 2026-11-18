"""seed_questions 测试：采样 / JSON 提取 / 完整生成流程（mock LLM）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from enterprise_kb import seed_questions as sq
from enterprise_kb.seed_questions import SeedQuestion


def make_chunks(n: int, start: int = 0) -> list[dict]:
    """造 n 个长度足够的 chunk（text > MIN_CHUNK_LEN）。"""
    return [
        {
            "id": f"id-{i}",
            "text": f"这是第 {i} 个片段的测试文本内容，长度足够超过阈值以通过过滤。",
            "meta": {},
        }
        for i in range(start, start + n)
    ]


# ---------- _sample_chunks ----------


def test_sample_filters_short():
    chunks = [
        {"id": "short", "text": "太短", "meta": {}},  # < MIN_CHUNK_LEN，过滤
        *make_chunks(1, start=1),  # 一个合法 chunk
    ]
    got = sq._sample_chunks(chunks, 5)
    assert len(got) == 1
    assert got[0]["id"] == "id-1"


def test_sample_uniform_when_more_than_n():
    chunks = make_chunks(10)
    got = sq._sample_chunks(chunks, 5)
    assert len(got) == 5
    # 均匀采样：步长 2，取 idx 0,2,4,6,8
    assert [c["id"] for c in got] == ["id-0", "id-2", "id-4", "id-6", "id-8"]


def test_sample_all_when_fewer_than_n():
    chunks = make_chunks(3)
    got = sq._sample_chunks(chunks, 10)
    assert len(got) == 3


def test_sample_empty_when_all_short():
    got = sq._sample_chunks([{"id": "s", "text": "x", "meta": {}}], 5)
    assert got == []


# ---------- _extract_json ----------


def test_extract_json_plain():
    assert sq._extract_json('{"items": []}') == {"items": []}


def test_extract_json_codeblock():
    text = '```json\n{"items": [{"index": 0}]}\n```'
    assert sq._extract_json(text) == {"items": [{"index": 0}]}


def test_extract_json_impurity():
    text = '好的，以下是结果：\n{"items": [{"index": 1}]}\n希望有帮助'
    assert sq._extract_json(text) == {"items": [{"index": 1}]}


def test_extract_json_invalid():
    with pytest.raises(ValueError):
        sq._extract_json("这不是 JSON")


# ---------- generate_seed_questions（mock LLM） ----------


def _fake_llm(content: str):
    def _fn(messages, model=None):
        return SimpleNamespace(content=content)

    return _fn


def test_generate_full_flow(monkeypatch):
    chunks = make_chunks(4)
    fake_content = json.dumps(
        {
            "items": [
                {"index": 0, "question": "Q0", "answer": "A0"},
                {"index": 2, "question": "Q2", "answer": "A2"},
            ]
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(sq, "_llm_generate", _fake_llm(fake_content))

    out = sq.generate_seed_questions(chunks, n=4)
    assert len(out) == 2
    assert isinstance(out[0], SeedQuestion)
    assert out[0].question == "Q0"
    assert out[0].source_chunk_ids == ["id-0"]
    assert out[1].source_chunk_ids == ["id-2"]


def test_generate_batches(monkeypatch):
    """batch_size=2 时，6 个 chunk 触发 3 次 LLM 调用。"""
    chunks = make_chunks(6)
    calls = []

    def _fn(messages, model=None):
        # 从 prompt 里反向推断本批的 chunk index（user content 含 [i] 标记）
        user = messages[1]["content"]
        import re

        idxs = [int(x) for x in re.findall(r"\[(\d+)\]", user)]
        items = [{"index": j, "question": f"Q{i}", "answer": f"A{i}"} for j, i in enumerate(idxs)]
        calls.append(idxs)
        return SimpleNamespace(content=json.dumps({"items": items}, ensure_ascii=False))

    monkeypatch.setattr(sq, "_llm_generate", _fn)

    out = sq.generate_seed_questions(chunks, n=6, batch_size=2)
    assert len(calls) == 3
    assert len(out) == 6
    assert sorted(q.source_chunk_ids[0] for q in out) == [f"id-{i}" for i in range(6)]


def test_generate_skips_invalid_item(monkeypatch):
    chunks = make_chunks(2)
    fake_content = json.dumps(
        {
            "items": [
                {"index": 0, "question": "Q0", "answer": "A0"},
                {"index": 99, "question": "越界", "answer": "A"},  # 越界 index → 跳过
                "不是 dict",  # 非 dict → 跳过
            ]
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(sq, "_llm_generate", _fake_llm(fake_content))

    out = sq.generate_seed_questions(chunks, n=2)
    assert len(out) == 1
    assert out[0].question == "Q0"


def test_generate_parse_fail_returns_empty(monkeypatch):
    chunks = make_chunks(2)
    monkeypatch.setattr(sq, "_llm_generate", _fake_llm("这不是 JSON"))

    out = sq.generate_seed_questions(chunks, n=2)
    assert out == []


def test_generate_empty_chunks(monkeypatch):
    # 全过短 → 直接返回空，不调用 LLM
    out = sq.generate_seed_questions([{"id": "s", "text": "x", "meta": {}}], n=5)
    assert out == []

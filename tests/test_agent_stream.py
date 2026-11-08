"""agent 流式层测试（spec 8 / F1-F3 / F9）。

mock 掉 agent.astream_events，验证 astream() 的事件转换逻辑
（reasoning / tool / text_delta / citations / done / error）。
"""

from __future__ import annotations

import asyncio

import pytest

from enterprise_kb import agent as agent_mod
from enterprise_kb.agent import _extract_tool_output


class FakeChunk:
    def __init__(self, content="", additional_kwargs=None):
        self.content = content
        self.additional_kwargs = additional_kwargs or {}


class FakeToolMessage:
    def __init__(self, content, artifact=None):
        self.content = content
        self.artifact = artifact


class FakeAgent:
    def __init__(self, events):
        self.events = events

    async def astream_events(self, input, version="v2"):
        for e in self.events:
            yield e


def _collect(events):
    async def run():
        agent_mod._get_agent = lambda lang: FakeAgent(events)
        return [e async for e in agent_mod.astream("问题")]

    return asyncio.run(run())


def test_astream_reasoning_and_text(monkeypatch):
    events = [
        {"event": "on_chat_model_start", "data": {}},
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": FakeChunk(additional_kwargs={"reasoning_content": "先思考"})},
        },
        {
            "event": "on_chat_model_stream",
            "data": {"chunk": FakeChunk(content="答案是")},
        },
    ]
    out = _collect(events)
    types = [e["type"] for e in out]
    assert types == [
        "reasoning_start",
        "reasoning_delta",
        "reasoning_end",
        "text_delta",
        "done",
    ]
    assert out[0]["step"] == 1
    assert out[1]["delta"] == "先思考"
    assert out[3]["delta"] == "答案是"
    # done 的 answer 聚合 text_delta
    assert out[4]["answer"] == "答案是"


def test_astream_tool_and_citations(monkeypatch):
    events = [
        {"event": "on_chat_model_start", "data": {}},
        {
            "event": "on_tool_start",
            "run_id": "t1",
            "name": "kb_search",
            "data": {"input": {"query": "k8s"}},
        },
        {
            "event": "on_tool_end",
            "run_id": "t1",
            "name": "kb_search",
            "data": {
                "output": FakeToolMessage(
                    content="[1] 片段",
                    artifact=[{"title": "t", "url": None, "snippet": "s"}],
                )
            },
        },
    ]
    out = _collect(events)
    types = [e["type"] for e in out]
    assert "tool_start" in types
    assert "tool_end" in types
    assert "citations" in types

    tool_start = next(e for e in out if e["type"] == "tool_start")
    assert tool_start["id"] == "t1"
    assert tool_start["name"] == "kb_search"
    assert tool_start["args"] == {"query": "k8s"}

    tool_end = next(e for e in out if e["type"] == "tool_end")
    assert tool_end["output"] == "[1] 片段"
    assert tool_end["status"] == "success"
    assert "duration_ms" in tool_end

    citations = next(e for e in out if e["type"] == "citations")
    assert citations["sources"][0]["title"] == "t"


def test_astream_error(monkeypatch):
    class BoomAgent:
        async def astream_events(self, input, version="v2"):
            raise RuntimeError("boom")
            yield  # pragma: no cover

    async def run():
        agent_mod._get_agent = lambda lang: BoomAgent()
        return [e async for e in agent_mod.astream("问题")]

    out = asyncio.run(run())
    assert out[-1]["type"] == "error"
    assert "boom" in out[-1]["message"]


# ---------- _extract_tool_output ----------


def test_extract_none():
    assert _extract_tool_output(None) == ("", None)


def test_extract_plain_str():
    assert _extract_tool_output("hello") == ("hello", None)


def test_extract_toolmessage_with_artifact():
    content, artifact = _extract_tool_output(
        FakeToolMessage("text", [{"title": "t"}])
    )
    assert content == "text"
    assert artifact == [{"title": "t"}]


def test_extract_toolmessage_no_artifact():
    content, artifact = _extract_tool_output(FakeToolMessage("text"))
    assert content == "text"
    assert artifact is None


def test_extract_non_list_artifact_ignored():
    content, artifact = _extract_tool_output(FakeToolMessage("text", "not-a-list"))
    assert content == "text"
    assert artifact is None

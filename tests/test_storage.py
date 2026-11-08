"""storage 层测试：会话/消息 CRUD + tool_trace 序列化往返。"""

from __future__ import annotations

import pytest

from enterprise_kb import storage
from enterprise_kb.config import get_settings


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """隔离数据库路径，避免污染真实 data/chat.db。"""
    monkeypatch.setenv("UI__DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_session_crud(tmp_db):
    s = storage.create_session(title="第一个会话")
    assert s.id
    assert s.title == "第一个会话"
    assert s.created_at

    # get
    got = storage.get_session(s.id)
    assert got is not None
    assert got.title == "第一个会话"

    # rename
    assert storage.rename_session(s.id, "改名了")
    assert storage.get_session(s.id).title == "改名了"

    # delete
    assert storage.delete_session(s.id)
    assert storage.get_session(s.id) is None

    # rename/delete 不存在 → False
    assert not storage.rename_session("不存在", "x")
    assert not storage.delete_session("不存在")


def test_list_sessions_sorted_by_updated_at(tmp_db):
    a = storage.create_session("A")
    b = storage.create_session("B")
    # 更新 A（加消息），A 应排到最前
    storage.add_message(a.id, "user", "hello")
    sessions = storage.list_sessions()
    assert sessions[0].id == a.id


def test_message_and_auto_title(tmp_db):
    s = storage.create_session()
    storage.add_message(s.id, "user", "我的 Pod 为什么一直重启呢？")
    # 自动标题 = 首条用户消息前 N 字
    assert storage.get_session(s.id).title == "我的 Pod 为什么一直重启呢？"


def test_tool_trace_roundtrip(tmp_db):
    s = storage.create_session("trace")
    trace = [
        storage.ToolCall(name="k8s_get", args={"kind": "node", "name": "fake-node-0"}, output="NAME ...", duration_ms=12),
        storage.ToolCall(name="web_search", args={"query": "k8s"}, output="[1] ...", status="success"),
    ]
    storage.add_message(s.id, "user", "问题")
    storage.add_message(s.id, "assistant", "回答", tool_trace=trace)

    msgs = storage.get_messages(s.id)
    assert len(msgs) == 2
    assistant = msgs[1]
    assert assistant.role == "assistant"
    assert len(assistant.tool_trace) == 2
    assert assistant.tool_trace[0].name == "k8s_get"
    assert assistant.tool_trace[0].args == {"kind": "node", "name": "fake-node-0"}
    assert assistant.tool_trace[0].duration_ms == 12


def test_delete_session_cascades_messages(tmp_db):
    s = storage.create_session("级联")
    storage.add_message(s.id, "user", "hi")
    assert len(storage.get_messages(s.id)) == 1
    storage.delete_session(s.id)
    # 消息随会话删除（外键 ON DELETE CASCADE）
    assert storage.get_messages(s.id) == []

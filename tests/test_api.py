"""api 层测试：会话管理 REST（不触发 LLM，只测 CRUD）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from enterprise_kb.api import app
from enterprise_kb.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UI__DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_sessions_crud(client):
    # create
    r = client.post("/api/sessions", json={"title": "测试会话"})
    assert r.status_code == 200
    sid = r.json()["id"]
    assert r.json()["title"] == "测试会话"

    # list
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json())

    # get（含 messages）
    r = client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid
    assert r.json()["messages"] == []

    # rename
    r = client.patch(f"/api/sessions/{sid}", json={"title": "改名"})
    assert r.status_code == 200
    assert client.get(f"/api/sessions/{sid}").json()["title"] == "改名"

    # delete
    r = client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_get_nonexistent_session_404(client):
    assert client.get("/api/sessions/nonexistent").status_code == 404
    assert client.patch("/api/sessions/nonexistent", json={"title": "x"}).status_code == 404
    assert client.delete("/api/sessions/nonexistent").status_code == 404


# ---------- 停止生成（F6）----------


def test_cancel_returns_ok(client):
    # cancel 幂等：任意 run_id 都返回 ok（即使不存在）
    r = client.post("/api/chat/nonexistent-run-id/cancel")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_cancel_sets_event(client):
    import asyncio

    from enterprise_kb import api

    ev = asyncio.Event()
    api._cancel_events["test-run"] = ev
    try:
        r = client.post("/api/chat/test-run/cancel")
        assert r.json() == {"ok": True}
        assert ev.is_set()
    finally:
        api._cancel_events.pop("test-run", None)

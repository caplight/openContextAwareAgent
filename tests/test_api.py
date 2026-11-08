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

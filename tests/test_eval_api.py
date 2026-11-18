"""eval_api 测试：评估闭环 REST 端点（mock 掉 LLM/索引/Qdrant 依赖）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from enterprise_kb import eval_api
from enterprise_kb.api import app
from enterprise_kb.assistant import AssistantConfig, resolve
from enterprise_kb.config import get_settings
from enterprise_kb.evaluate import EvaluationResult
from enterprise_kb.suggest import Suggestion


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UI__DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DOCS_DIR", str(tmp_path / "docs"))
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _seed_q(n=2):
    return [
        {"question": f"q{i}", "expected_answer": f"a{i}"}
        for i in range(n)
    ]


# ---------- 1. 上传 ----------

def test_upload_rejects_bad_type(client):
    r = client.post("/api/eval/upload", files={"file": ("a.exe", b"x", "application/octet-stream")})
    assert r.status_code == 400


def test_upload_indexes(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        eval_api.ingest, "load_and_split", lambda d: [{"id": "c1", "text": "hi", "meta": {}}]
    )
    monkeypatch.setattr(eval_api.embed, "index_chunks", lambda chunks: len(chunks))

    r = client.post("/api/eval/upload", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["filename"] == "a.pdf"
    assert body["chunk_count"] == 1
    # 文件确实写到了 docs_dir
    assert (tmp_path / "docs" / "a.pdf").exists()


# ---------- 2. 种子问题 ----------

def test_seed_questions_empty_docs(client, monkeypatch):
    monkeypatch.setattr(eval_api.ingest, "load_and_split", lambda d=None: [])
    r = client.post("/api/eval/seed-questions", json={"n": 25})
    assert r.status_code == 400


def test_seed_questions_returns_questions(client, monkeypatch):
    from enterprise_kb.seed_questions import SeedQuestion

    monkeypatch.setattr(
        eval_api.ingest, "load_and_split", lambda d=None: [{"id": "c1", "text": "hi", "meta": {}}]
    )
    monkeypatch.setattr(
        eval_api,
        "generate_seed_questions",
        lambda chunks, n=25: [SeedQuestion(question="q1", expected_answer="a1")],
    )
    r = client.post("/api/eval/seed-questions", json={"n": 25})
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert len(qs) == 1
    assert qs[0]["question"] == "q1"


# ---------- 3. 评估 ----------

def test_evaluate_empty_questions(client):
    r = client.post("/api/eval/evaluate", json={"questions": []})
    assert r.status_code == 400


def test_evaluate_returns_results(client, monkeypatch):
    result = EvaluationResult(
        question="q1", expected_answer="a1", answer="ans",
        contexts=["c1"], faithfulness=0.8, context_precision=0.7,
    )
    monkeypatch.setattr(
        eval_api, "run_evaluation",
        lambda questions, config=None, judge_model="deepseek-chat": SimpleNamespace(results=[result]),
    )
    r = client.post("/api/eval/evaluate", json={"questions": _seed_q()})
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["question"] == "q1"
    assert results[0]["faithfulness"] == 0.8


# ---------- 4. 建议 ----------

def test_suggest_returns_suggestion(client, monkeypatch):
    s = Suggestion(param="top_k", current=5, recommended=8, reason="更高", confidence=0.6)
    monkeypatch.setattr(
        eval_api, "suggest_top_k_workflow",
        lambda aid, questions, ratings=None, candidates=(3, 5, 8, 10): s,
    )
    r = client.post("/api/eval/suggest", json={"questions": _seed_q(), "ratings": []})
    assert r.status_code == 200
    body = r.json()["suggestion"]
    assert body["recommended"] == 8
    assert body["current"] == 5


def test_suggest_none(client, monkeypatch):
    monkeypatch.setattr(
        eval_api, "suggest_top_k_workflow", lambda aid, questions, ratings=None: None
    )
    r = client.post("/api/eval/suggest", json={"questions": _seed_q()})
    assert r.status_code == 200
    assert r.json()["suggestion"] is None


# ---------- 5. 采纳 ----------

def test_apply_writes_top_k(client, monkeypatch):
    resolved = resolve(AssistantConfig(top_k=8))
    monkeypatch.setattr(eval_api, "apply_suggestion", lambda aid, s: resolved)
    r = client.post(
        "/api/eval/apply",
        json={
            "param": "top_k", "current": 5, "recommended": 8,
            "reason": "更高", "confidence": 0.6, "category": "weak",
        },
    )
    assert r.status_code == 200
    assert r.json()["top_k"] == 8

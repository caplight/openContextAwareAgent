"""storage_eval 测试：评估运行 + 评分的持久化往返。"""

from __future__ import annotations

import pytest

from enterprise_kb import storage_eval
from enterprise_kb.config import get_settings
from enterprise_kb.storage_eval import (
    EvaluationRunRecord,
    RatingRecord,
    delete_evaluation_run,
    get_evaluation_run,
    get_latest_run,
    get_ratings,
    save_evaluation_run,
    save_rating,
)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """隔离 db 路径（复用 ui.db_path 目录 → 独立 eval.db）。"""
    monkeypatch.setenv("UI__DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _save_run(assistant_id="aid-1", snapshot=None, n=25):
    return save_evaluation_run(
        assistant_id,
        snapshot or {"top_k": 5, "generative_model": "deepseek/deepseek-chat"},
        n,
    )


def test_save_and_get_run_roundtrip(tmp_db):
    snapshot = {"top_k": 5, "generative_model": "deepseek/deepseek-chat", "temperature": 0.0}
    rid = _save_run(snapshot=snapshot, n=30)

    r = get_evaluation_run(rid)
    assert isinstance(r, EvaluationRunRecord)
    assert r.assistant_id == "aid-1"
    assert r.config_snapshot == snapshot  # dict 完整往返（含 0.0）
    assert r.seed_questions == 30


def test_get_run_not_found(tmp_db):
    assert get_evaluation_run("nonexistent") is None


def test_save_and_get_rating_roundtrip(tmp_db):
    rid = _save_run()
    rating_id = save_rating(rid, "问题1", "up")

    ratings = get_ratings(rid)
    assert len(ratings) == 1
    r = ratings[0]
    assert isinstance(r, RatingRecord)
    assert r.rating_id == rating_id
    assert r.question == "问题1"
    assert r.rating == "up"


def test_get_ratings_ordered(tmp_db):
    rid = _save_run()
    save_rating(rid, "q1", "up")
    save_rating(rid, "q2", "down")
    save_rating(rid, "q3", "copied")

    ratings = get_ratings(rid)
    assert [r.question for r in ratings] == ["q1", "q2", "q3"]


def test_get_ratings_empty(tmp_db):
    rid = _save_run()
    assert get_ratings(rid) == []


def test_get_latest_run(tmp_db):
    _save_run(snapshot={"top_k": 5})          # 早
    _save_run(snapshot={"top_k": 8})          # 晚

    latest = get_latest_run("aid-1")
    assert latest.config_snapshot["top_k"] == 8


def test_get_latest_run_not_found(tmp_db):
    assert get_latest_run("no-such-aid") is None


def test_delete_run_cascades_ratings(tmp_db):
    rid = _save_run()
    save_rating(rid, "q1", "up")

    assert delete_evaluation_run(rid) is True
    assert get_evaluation_run(rid) is None
    assert get_ratings(rid) == []  # 外键 CASCADE 一起删


def test_delete_run_not_found(tmp_db):
    assert delete_evaluation_run("nonexistent") is False

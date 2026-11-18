"""评估数据持久化：evaluation_run + rating（golden_case 后置）。

设计见 `docs/mvp-design.md` §2.3–2.5。

沿用 `storage.py` / `assistant.py` 的模式：标准库 sqlite3 + 每操作独立建连 + pydantic。
独立 `eval.db`（不污染会话库 `ui.db`，也不混入 `assistant.db` 的配置）。

注意：`assistant_id` 是**逻辑关联**（跨 db 无外键），`ratings.run_id` 是同 db 内 FK
（`ON DELETE CASCADE`，删 run 时评分一起删）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger
from enterprise_kb.rating import RatingValue

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> Path:
    s = get_settings()
    return Path(s.ui.db_path).parent / "eval.db"


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS evaluation_runs (
            run_id           TEXT PRIMARY KEY,
            assistant_id     TEXT NOT NULL,
            config_snapshot  TEXT NOT NULL,
            seed_questions   INTEGER NOT NULL,
            created_at       TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ratings (
            rating_id    TEXT PRIMARY KEY,
            run_id       TEXT NOT NULL,
            question     TEXT NOT NULL,
            rating       TEXT NOT NULL CHECK (rating IN ('up','down','copied','regenerated')),
            created_at   TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES evaluation_runs(run_id) ON DELETE CASCADE
        );
        """
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _init(conn)
    return conn


class EvaluationRunRecord(BaseModel):
    """一次评估运行（含配置快照，供后续 diff）。"""

    run_id: str
    assistant_id: str
    config_snapshot: dict
    seed_questions: int
    created_at: str


class RatingRecord(BaseModel):
    """一条用户评分（listwise）。"""

    rating_id: str
    run_id: str
    question: str
    rating: RatingValue
    created_at: str


def save_evaluation_run(
    assistant_id: str,
    config_snapshot: dict,
    seed_questions: int,
    run_id: str | None = None,
) -> str:
    """存一次评估运行，返回 run_id。"""
    rid = run_id or str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO evaluation_runs (run_id, assistant_id, config_snapshot, seed_questions, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (rid, assistant_id, json.dumps(config_snapshot), seed_questions, _now()),
        )
    return rid


def save_rating(
    run_id: str,
    question: str,
    rating: RatingValue,
    rating_id: str | None = None,
) -> str:
    """存一条评分，返回 rating_id。"""
    rid = rating_id or str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ratings (rating_id, run_id, question, rating, created_at) VALUES (?, ?, ?, ?, ?)",
            (rid, run_id, question, rating, _now()),
        )
    return rid


def get_evaluation_run(run_id: str) -> EvaluationRunRecord | None:
    """读一次评估运行。不存在返回 None。"""
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM evaluation_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if r is None:
        return None
    return EvaluationRunRecord(
        run_id=r["run_id"],
        assistant_id=r["assistant_id"],
        config_snapshot=json.loads(r["config_snapshot"]),
        seed_questions=r["seed_questions"],
        created_at=r["created_at"],
    )


def get_ratings(run_id: str) -> list[RatingRecord]:
    """读某次运行的所有评分（按创建时间升序）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM ratings WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
    return [
        RatingRecord(
            rating_id=r["rating_id"],
            run_id=r["run_id"],
            question=r["question"],
            rating=r["rating"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_latest_run(assistant_id: str) -> EvaluationRunRecord | None:
    """读该助手最近一次评估运行。无记录返回 None。"""
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM evaluation_runs WHERE assistant_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (assistant_id,),
        ).fetchone()
    if r is None:
        return None
    return EvaluationRunRecord(
        run_id=r["run_id"],
        assistant_id=r["assistant_id"],
        config_snapshot=json.loads(r["config_snapshot"]),
        seed_questions=r["seed_questions"],
        created_at=r["created_at"],
    )


def delete_evaluation_run(run_id: str) -> bool:
    """删除一次运行（评分随外键 CASCADE 一起删）。"""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM evaluation_runs WHERE run_id = ?", (run_id,))
    return cur.rowcount > 0

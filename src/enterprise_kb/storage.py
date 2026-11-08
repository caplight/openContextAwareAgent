"""SQLite 会话持久化（spec Q1：单文件 data/chat.db，单用户无登录）。

会话/消息数据模型 + CRUD。用标准库 sqlite3（零新依赖）。FastAPI 多线程下
每次操作独立建连（sqlite3 连接不能跨线程共享），避免连接池复杂度。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

# 自动生成会话标题时，取首条用户消息的前 N 字
_TITLE_PREFIX_LEN = 40


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> str:
    p = get_settings().ui.db_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


@dataclass
class ToolCall:
    """一次工具调用（内嵌在消息里，不单独建表）。"""

    name: str
    args: dict = field(default_factory=dict)
    output: str = ""
    status: str = "success"  # running | success | error
    duration_ms: int = 0


@dataclass
class Message:
    id: str
    role: str  # user | assistant
    content: str = ""
    tool_trace: list[ToolCall] = field(default_factory=list)
    created_at: str = ""


@dataclass
class Session:
    id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id         TEXT PRIMARY KEY,
            title      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id         TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL DEFAULT '',
            tool_trace TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        """
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _init(conn)
    return conn


# ---------- Session ----------

def create_session(title: str = "") -> Session:
    sid = str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, title, now, now),
        )
    return Session(id=sid, title=title, created_at=now, updated_at=now)


def list_sessions() -> list[Session]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [Session(id=r["id"], title=r["title"], created_at=r["created_at"], updated_at=r["updated_at"]) for r in rows]


def get_session(session_id: str) -> Session | None:
    with _connect() as conn:
        r = conn.execute("SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if r is None:
        return None
    return Session(id=r["id"], title=r["title"], created_at=r["created_at"], updated_at=r["updated_at"])


def rename_session(session_id: str, title: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?", (title, _now(), session_id))
    return cur.rowcount > 0


def delete_session(session_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return cur.rowcount > 0


# ---------- Message ----------

def add_message(
    session_id: str,
    role: str,
    content: str,
    tool_trace: list[ToolCall] | None = None,
) -> Message:
    mid = str(uuid.uuid4())
    now = _now()
    trace_json = json.dumps([asdict(t) for t in (tool_trace or [])], ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, tool_trace, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (mid, session_id, role, content, trace_json, now),
        )
        # 若会话标题为空，用首条用户消息自动命名
        if role == "user":
            conn.execute(
                "UPDATE sessions SET title = CASE WHEN title = '' THEN ? ELSE title END, updated_at = ? WHERE id = ?",
                (_auto_title(content), now, session_id),
            )
    return Message(id=mid, role=role, content=content, tool_trace=tool_trace or [], created_at=now)


def get_messages(session_id: str) -> list[Message]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, tool_trace, created_at FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        try:
            trace = [ToolCall(**t) for t in json.loads(r["tool_trace"] or "[]")]
        except (json.JSONDecodeError, TypeError):
            trace = []
        out.append(Message(id=r["id"], role=r["role"], content=r["content"], tool_trace=trace, created_at=r["created_at"]))
    return out


def _auto_title(content: str) -> str:
    text = " ".join(content.split())
    return text[: _TITLE_PREFIX_LEN] + ("…" if len(text) > _TITLE_PREFIX_LEN else "")

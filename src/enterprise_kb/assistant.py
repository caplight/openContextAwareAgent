"""每助手一份的可调配置（per-assistant config）。

从全局 `Settings`（`config.py`，部署级单例）中拆出「助手级可调参数」，
每个助手（assistant）一份 `AssistantConfig`，未覆盖的字段回退全局。

设计见 `docs/assistant-config-design.md`。

存储沿用 `storage.py` 的模式：标准库 sqlite3 + 每操作独立建连 + dataclass/pydantic。
db 路径复用 `ui.db_path` 的目录，独立文件名 `assistant.db`（避免污染会话库，
同时保留 config-driven 的目录隔离，测试可用 `UI__DB_PATH` 环境变量隔离）。
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _db_path() -> Path:
    """复用 ui.db_path 的目录，独立文件名 assistant.db。"""
    p = get_settings().ui.db_path
    path = p.parent / "assistant.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------- 数据模型 ----------


class AssistantConfig(BaseModel):
    """每助手一份的可调配置（三档参数）。

    哨兵值约定：空字符串 / -1 / -1.0 / None 表示「未覆盖，回退全局 Settings」。
    单条记录只存用户改过的字段，避免全量冗余。
    """

    # 强建议档（离散、证据清晰）
    generative_model: str = ""            # 空 = 用全局 llm.primary
    embedding_model: str = ""             # 空 = 用全局 embedding.model

    # 用户自滑档（成本/质量权衡）
    top_k: int = -1                       # -1 = 用全局 retrieval.top_k
    chunk_size: int = -1                  # -1 = 用全局 retrieval.chunk_size
    rerank_enabled: bool | None = None    # None = 用全局行为（默认不 rerank）

    # 用户自选档
    vector_store: str = "qdrant"          # 当前仅 "qdrant"

    # 不暴露档（默认值，通常不展示）
    chunk_overlap: int = -1               # -1 = 用全局 retrieval.chunk_overlap
    temperature: float = -1.0             # -1 = 用全局 llm.temperature


class ResolvedConfig(BaseModel):
    """`resolve()` 后的实际值（哨兵值已替换为全局 Settings 的对应字段）。"""

    generative_model: str
    embedding_model: str
    top_k: int
    chunk_size: int
    chunk_overlap: int
    rerank_enabled: bool
    vector_store: str
    temperature: float


def resolve(cfg: AssistantConfig | None = None) -> ResolvedConfig:
    """把哨兵值解析为实际值（未覆盖字段回退全局 Settings）。"""
    s = get_settings()
    cfg = cfg or AssistantConfig()
    return ResolvedConfig(
        generative_model=cfg.generative_model or s.llm.primary,
        embedding_model=cfg.embedding_model or s.embedding.model,
        top_k=cfg.top_k if cfg.top_k > 0 else s.retrieval.top_k,
        chunk_size=cfg.chunk_size if cfg.chunk_size > 0 else s.retrieval.chunk_size,
        chunk_overlap=cfg.chunk_overlap if cfg.chunk_overlap > 0 else s.retrieval.chunk_overlap,
        rerank_enabled=cfg.rerank_enabled if cfg.rerank_enabled is not None else False,
        vector_store=cfg.vector_store,
        temperature=cfg.temperature if cfg.temperature >= 0 else s.llm.temperature,
    )


# ---------- 存储 ----------


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS assistants (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            template    TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assistant_configs (
            assistant_id  TEXT PRIMARY KEY,
            config_json   TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
        );
        """
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _init(conn)
    return conn


def create_assistant(
    name: str,
    template: str | None = None,
    config: AssistantConfig | None = None,
) -> str:
    """创建助手，返回 assistant_id。可选传入初始配置。"""
    aid = str(uuid.uuid4())
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO assistants (id, name, template, created_at) VALUES (?, ?, ?, ?)",
            (aid, name, template, now),
        )
        if config is not None:
            conn.execute(
                "INSERT INTO assistant_configs (assistant_id, config_json, updated_at) VALUES (?, ?, ?)",
                (aid, config.model_dump_json(), now),
            )
    return aid


def upsert_assistant_config(assistant_id: str, config: AssistantConfig) -> None:
    """写入/覆盖助手配置（整条 JSON，ON CONFLICT 更新）。"""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO assistant_configs (assistant_id, config_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(assistant_id) DO UPDATE SET
                config_json = excluded.config_json,
                updated_at  = excluded.updated_at
            """,
            (assistant_id, config.model_dump_json(), _now()),
        )


def get_assistant_config(assistant_id: str) -> AssistantConfig | None:
    """读取助手配置。不存在则返回 None。"""
    with _connect() as conn:
        r = conn.execute(
            "SELECT config_json FROM assistant_configs WHERE assistant_id = ?",
            (assistant_id,),
        ).fetchone()
    if r is None:
        return None
    return AssistantConfig.model_validate_json(r["config_json"])


def load_assistant_config(assistant_id: str | None) -> AssistantConfig:
    """加载助手配置。assistant_id 为 None 或不存在时，返回全默认（哨兵值）。"""
    if assistant_id is None:
        return AssistantConfig()
    stored = get_assistant_config(assistant_id)
    return stored if stored is not None else AssistantConfig()


def get_resolved_config(assistant_id: str | None) -> ResolvedConfig:
    """加载并 resolve（一步到位：哨兵值 → 实际值）。"""
    return resolve(load_assistant_config(assistant_id))


def delete_assistant(assistant_id: str) -> bool:
    """删除助手（配置随外键 ON DELETE CASCADE 一起删）。"""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM assistants WHERE id = ?", (assistant_id,))
    return cur.rowcount > 0

"""assistant 层测试：每助手配置的 resolve 哨兵值回退 + CRUD 往返。"""

from __future__ import annotations

import pytest

from enterprise_kb import assistant
from enterprise_kb.assistant import AssistantConfig, ResolvedConfig
from enterprise_kb.config import get_settings


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """隔离 db 路径（复用 ui.db_path 目录 → 独立 assistant.db）。"""
    monkeypatch.setenv("UI__DB_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- resolve：哨兵值回退 ----------


def test_resolve_all_default(tmp_db):
    """空配置 → 全部回退全局 Settings。"""
    s = get_settings()
    r = assistant.resolve(AssistantConfig())
    assert r.generative_model == s.llm.primary
    assert r.embedding_model == s.embedding.model
    assert r.top_k == s.retrieval.top_k
    assert r.chunk_size == s.retrieval.chunk_size
    assert r.chunk_overlap == s.retrieval.chunk_overlap
    assert r.temperature == s.llm.temperature
    assert r.rerank_enabled is False  # 默认不 rerank
    assert r.vector_store == "qdrant"


def test_resolve_none_cfg(tmp_db):
    """resolve(None) 等价于 resolve(默认配置)。"""
    r1 = assistant.resolve(None)
    r2 = assistant.resolve(AssistantConfig())
    assert r1 == r2


def test_resolve_partial_override(tmp_db):
    """只覆盖 top_k，其余字段回退全局。"""
    s = get_settings()
    r = assistant.resolve(AssistantConfig(top_k=8))
    assert r.top_k == 8                       # 覆盖生效
    assert r.chunk_size == s.retrieval.chunk_size  # 其余回退
    assert r.generative_model == s.llm.primary


def test_resolve_temperature_sentinel(tmp_db):
    """temperature=0.0 是合法值，不应被当作哨兵（-1.0 才回退）。"""
    r0 = assistant.resolve(AssistantConfig(temperature=0.0))
    assert r0.temperature == 0.0
    r_default = assistant.resolve(AssistantConfig(temperature=-1.0))
    assert r_default.temperature == get_settings().llm.temperature


def test_resolve_rerank_enabled(tmp_db):
    """rerank_enabled 显式 True/False 都覆盖；None 回退默认 False。"""
    assert assistant.resolve(AssistantConfig(rerank_enabled=True)).rerank_enabled is True
    assert assistant.resolve(AssistantConfig(rerank_enabled=False)).rerank_enabled is False
    assert assistant.resolve(AssistantConfig(rerank_enabled=None)).rerank_enabled is False


# ---------- CRUD 往返 ----------


def test_create_and_get_config_roundtrip(tmp_db):
    cfg = AssistantConfig(top_k=8, generative_model="deepseek/deepseek-v4-pro", rerank_enabled=True)
    aid = assistant.create_assistant("测试助手", template="devops", config=cfg)

    got = assistant.get_assistant_config(aid)
    assert got is not None
    assert got.top_k == 8
    assert got.generative_model == "deepseek/deepseek-v4-pro"
    assert got.rerank_enabled is True
    # 未设置的字段保持哨兵值
    assert got.chunk_size == -1
    assert got.embedding_model == ""


def test_get_config_nonexistent(tmp_db):
    assert assistant.get_assistant_config("不存在") is None


def test_upsert_overwrites(tmp_db):
    aid = assistant.create_assistant("助手", config=AssistantConfig(top_k=3))
    # 先 upsert 一次
    assistant.upsert_assistant_config(aid, AssistantConfig(top_k=10))
    assert assistant.get_assistant_config(aid).top_k == 10
    # 再 upsert 覆盖
    assistant.upsert_assistant_config(aid, AssistantConfig(top_k=20, chunk_size=1024))
    got = assistant.get_assistant_config(aid)
    assert got.top_k == 20
    assert got.chunk_size == 1024


def test_load_assistant_config(tmp_db):
    # None → 全默认
    assert assistant.load_assistant_config(None) == AssistantConfig()
    # 不存在 → 全默认
    assert assistant.load_assistant_config("不存在") == AssistantConfig()
    # 存在 → 返回存储值
    aid = assistant.create_assistant("A", config=AssistantConfig(top_k=7))
    assert assistant.load_assistant_config(aid).top_k == 7


def test_get_resolved_config(tmp_db):
    """加载 + resolve 一步到位。"""
    aid = assistant.create_assistant("A", config=AssistantConfig(top_k=9))
    r = assistant.get_resolved_config(aid)
    assert isinstance(r, ResolvedConfig)
    assert r.top_k == 9
    assert r.chunk_size == get_settings().retrieval.chunk_size  # 未覆盖字段回退


def test_delete_cascades_config(tmp_db):
    """删除助手应级联删除配置（外键 ON DELETE CASCADE）。"""
    aid = assistant.create_assistant("A", config=AssistantConfig(top_k=5))
    assert assistant.get_assistant_config(aid) is not None
    assert assistant.delete_assistant(aid) is True
    assert assistant.get_assistant_config(aid) is None


def test_delete_nonexistent(tmp_db):
    """删除不存在的助手 → False。"""
    assert assistant.delete_assistant("不存在") is False

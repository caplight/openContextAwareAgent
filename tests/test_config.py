"""配置层测试：默认值 / 环境变量覆盖 / SecretStr 保护。"""

from __future__ import annotations

from enterprise_kb.config import Settings, get_settings


def test_defaults(monkeypatch):
    # .env 里 EMBEDDING__MODEL 指向本地模型路径，这里隔离它测代码默认值
    monkeypatch.setenv("EMBEDDING__MODEL", "BAAI/bge-m3")
    s = Settings()
    assert s.qdrant.collection == "enterprise_kb"
    assert s.embedding.model == "BAAI/bge-m3"
    assert s.embedding.dim == 1024
    assert s.llm.primary == "deepseek/deepseek-flash"
    assert s.llm.fallback == "deepseek/deepseek-v4-pro"
    assert s.retrieval.top_k == 5
    assert s.context.max_tokens == 8000
    assert s.context.keep_turns == 3


def test_env_override(monkeypatch):
    monkeypatch.setenv("QDRANT__COLLECTION", "test_kb")
    monkeypatch.setenv("LLM__FALLBACK", "deepseek/deepseek-chat")
    monkeypatch.setenv("RETRIEVAL__TOP_K", "10")
    s = Settings()
    assert s.qdrant.collection == "test_kb"
    assert s.llm.fallback == "deepseek/deepseek-chat"
    assert s.retrieval.top_k == 10


def test_secret_key_not_leaked(monkeypatch):
    """API key 用 SecretStr，repr 不泄露明文。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-123")
    s = Settings()
    assert s.deepseek_api_key is not None
    assert s.deepseek_api_key.get_secret_value() == "sk-test-123"
    assert "sk-test-123" not in repr(s.deepseek_api_key)


def test_get_settings_singleton():
    a = get_settings()
    b = get_settings()
    assert a is b

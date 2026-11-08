"""集中配置（config-driven 设计）。

- 所有可调参数类型安全（pydantic-settings + nested model）
- 环境变量可覆盖（`QDANT__URL`、`LLM__PRIMARY` 等，`__` 分隔 nested）
- API key 用 `SecretStr` 保护，只从环境变量读，绝不落盘
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# demo/ 项目根目录（config.py 在 src/enterprise_kb/ 下，上溯 3 级）
BASE_DIR = Path(__file__).resolve().parents[2]


class QdrantConfig(BaseModel):
    """向量库。url 为 None 时用 local mode（本地文件存储，无需 docker）。"""

    url: str | None = None
    path: str = "./data/qdrant"
    collection: str = "enterprise_kb"


class EmbeddingConfig(BaseModel):
    """本地 bge-m3 embedding。"""

    model: str = "BAAI/bge-m3"
    dim: int = 1024
    device: str = "auto"
    normalize: bool = True


class LLMConfig(BaseModel):
    """生成 LLM（经 LiteLLM，走 API）。"""

    primary: str = "deepseek/deepseek-flash"
    # fallback 也用 deepseek（当前无 anthropic key，claude 不可用）
    fallback: str = "deepseek/deepseek-v4-pro"
    temperature: float = 0.0


class RetrievalConfig(BaseModel):
    """检索 / 切分参数。"""

    top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 51


class ContextConfig(BaseModel):
    """上下文压缩参数（历史超限时的摘要 buffer）。"""

    max_tokens: int = 8000  # 历史超过此 token 数触发压缩
    keep_turns: int = 3  # 压缩后保留最近几轮原文


class RerankerConfig(BaseModel):
    """本地 bge-reranker-v2-m3 精排（cross-encoder）。"""

    model: str = "BAAI/bge-reranker-v2-m3"
    top_n: int = 20  # 混合检索先取 top-n 候选，reranker 再精排到 top_k


class LangfuseConfig(BaseModel):
    """可观测（可选，未启用时静默跳过）。"""

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"


class UIConfig(BaseModel):
    """Web UI 配置（spec 第 7 节）。"""

    default_lang: str = "en"  # en | zh
    default_theme: str = "dark"  # dark | light
    db_path: Path = BASE_DIR / "data" / "chat.db"  # SQLite 会话库
    sse_heartbeat_sec: int = 15  # SSE 心跳间隔（秒）
    session_ttl_days: int = 30  # 会话保留天数


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    qdrant: QdrantConfig = QdrantConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    llm: LLMConfig = LLMConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    context: ContextConfig = ContextConfig()
    reranker: RerankerConfig = RerankerConfig()
    langfuse: LangfuseConfig = LangfuseConfig()
    ui: UIConfig = UIConfig()

    # API key（仅环境变量注入，不落盘）
    anthropic_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    brave_api_key: SecretStr | None = None

    docs_dir: Path = BASE_DIR / "data" / "docs"


@lru_cache
def get_settings() -> Settings:
    """获取配置单例（测试可用 get_settings.cache_clear() 重置）。"""
    return Settings()

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

    primary: str = "claude-haiku-5-5"
    fallback: str = "deepseek/deepseek-flash"
    temperature: float = 0.0


class RetrievalConfig(BaseModel):
    """检索 / 切分参数。"""

    top_k: int = 5
    chunk_size: int = 512
    chunk_overlap: int = 51


class LangfuseConfig(BaseModel):
    """可观测（可选，未启用时静默跳过）。"""

    enabled: bool = False
    public_key: str = ""
    secret_key: str = ""
    host: str = "https://cloud.langfuse.com"


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
    langfuse: LangfuseConfig = LangfuseConfig()

    # API key（仅环境变量注入，不落盘）
    anthropic_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None

    docs_dir: Path = BASE_DIR / "data" / "docs"


@lru_cache
def get_settings() -> Settings:
    """获取配置单例（测试可用 get_settings.cache_clear() 重置）。"""
    return Settings()

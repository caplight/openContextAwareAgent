"""Embedding + 向量存储（M1.2）。

Phase 1 只做 dense 向量（bge-m3 的 1024 维 dense）。
sparse（BM25 式）+ multi-vector 留到 Phase 2 混合检索时启用。
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

# 模块级缓存，避免重复加载模型（bge-m3 约 2.2GB）
_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        settings = get_settings()
        # sentence-transformers 不支持 "auto" 字符串，None 表示自动检测（有 CUDA 用 CUDA，否则 CPU）
        device = None if settings.embedding.device == "auto" else settings.embedding.device
        logger.info(
            "加载 embedding 模型 %s (device=%s)",
            settings.embedding.model,
            device or "auto",
        )
        _model = SentenceTransformer(settings.embedding.model, device=device)
    return _model


def encode(texts: list[str]) -> list[list[float]]:
    """编码文本为 dense 向量（默认 1024 维，normalize 后余弦相似度用点积）。"""
    settings = get_settings()
    model = get_embedding_model()
    embs = model.encode(texts, normalize_embeddings=settings.embedding.normalize)
    return [e.tolist() for e in embs]


def get_client() -> QdrantClient:
    """获取 Qdrant client。url 为空时用 local mode（无需 docker）。"""
    settings = get_settings()
    if settings.qdrant.url:
        return QdrantClient(url=settings.qdrant.url)
    return QdrantClient(path=settings.qdrant.path)


def ensure_collection() -> None:
    """确保 collection 存在（不存在则创建）。"""
    client = get_client()
    settings = get_settings()
    existing = {c.name for c in client.get_collections().collections}
    if settings.qdrant.collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant.collection,
            vectors_config=VectorParams(size=settings.embedding.dim, distance=Distance.COSINE),
        )
        logger.info("创建 collection %s", settings.qdrant.collection)


def index_chunks(chunks: list[dict]) -> int:
    """把 chunks 编码后写入 Qdrant。chunk 结构：{"id", "text", "meta"}。"""
    if not chunks:
        return 0
    ensure_collection()
    settings = get_settings()
    client = get_client()

    texts = [c["text"] for c in chunks]
    vectors = encode(texts)

    points = [
        PointStruct(
            id=c["id"],
            vector=vectors[i],
            payload={"text": c["text"], "meta": c.get("meta", {})},
        )
        for i, c in enumerate(chunks)
    ]
    client.upsert(collection_name=settings.qdrant.collection, points=points)
    logger.info("写入 %d 个向量到 %s", len(points), settings.qdrant.collection)
    return len(points)

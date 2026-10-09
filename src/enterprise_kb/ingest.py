"""文档摄入（M1.1）：遍历 data/docs，加载 + 切分 → chunks。

支持 PDF / docx / md / txt，用 langchain loader + RecursiveCharacterTextSplitter。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

_SUPPORTED = {
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".md": TextLoader,
    ".txt": TextLoader,
    ".rst": TextLoader,
}


def _load_doc(path: Path):
    """根据扩展名选 loader 并加载。返回 langchain Document 列表。"""
    suffix = path.suffix.lower()
    loader_cls = _SUPPORTED.get(suffix)
    if loader_cls is None:
        return None
    if suffix in {".md", ".txt", ".rst"}:
        return loader_cls(str(path), encoding="utf-8").load()
    return loader_cls(str(path)).load()


def _chunk_id(text: str) -> str:
    """用内容 hash 生成稳定 id（去重）。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load_and_split(docs_dir: Path | None = None) -> list[dict]:
    """加载目录下所有支持的文档，切成 chunks。返回 [{"id", "text", "meta"}]。"""
    settings = get_settings()
    docs_dir = docs_dir or settings.docs_dir
    if not docs_dir.exists():
        logger.warning("文档目录不存在: %s", docs_dir)
        return []

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.retrieval.chunk_size,
        chunk_overlap=settings.retrieval.chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""],
    )

    chunks: list[dict] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            docs = _load_doc(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("跳过 %s: %s", path.name, e)
            continue
        if not docs:
            continue
        for doc in docs:
            for piece in splitter.split_text(doc.page_content):
                chunks.append(
                    {
                        "id": _chunk_id(piece),
                        "text": piece,
                        "meta": {**doc.metadata, "source": path.name},
                    }
                )
    logger.info("从 %s 切出 %d 个 chunks", docs_dir, len(chunks))
    return chunks

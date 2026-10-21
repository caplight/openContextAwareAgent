"""企业知识库智能助手（RAG demo）。

Phase 2b：混合召回（dense+BM25+RRF）→ rerank 精排 → 生成，全链路可观测（Langfuse）。
"""

from __future__ import annotations

import os

# 模型已本地缓存，禁用 huggingface_hub 联网检查（避免 Network unreachable 重试拖慢启动）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

__version__ = "0.1.0"

from enterprise_kb.graph import ask, build_graph  # noqa: F401

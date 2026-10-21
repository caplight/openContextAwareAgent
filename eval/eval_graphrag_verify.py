"""Phase 2c 验证脚本：LightRAG 跑通流程（小规模 100 段 + 多模式查询）。

用途：验证 LightRAG 能 insert（LLM 抽取实体关系）+ query（多模式检索生成），
拿到返回格式，供后续正式评测（eval_graphrag.py）设计参考。

只做 smoke test，不产出正式评测结果。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import numpy as np

from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc

# 项目 src 加入 path，复用 get_embedding_model
PROJECT = "/mnt/hgfs/VMWareShare/remote_jobs_research/demo"
sys.path.insert(0, os.path.join(PROJECT, "src"))

from enterprise_kb.embed import get_embedding_model  # noqa: E402

WORKING_DIR = os.path.join(PROJECT, ".tmp", "lightrag_verify")
CORPUS_PATH = os.path.join(PROJECT, "data", "eval", "golden_corpus.json")
SAMPLE_PATH = os.path.join(PROJECT, "data", "eval", "hotpotqa_sample.json")

N_CHUNKS = 100  # 先小规模跑通
N_QUERIES = 2   # 只测前 2 条问题
MODES = ["hybrid", "local", "global", "naive", "mix"]

DEEPSEEK_BASE = "https://api.deepseek.com"
LLM_MODEL = "deepseek-chat"
EMBED_DIM = 1024  # bge-m3 dense 维度

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = get_embedding_model()
    return _model


async def llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    return await openai_complete_if_cache(
        LLM_MODEL,
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=DEEPSEEK_BASE,
        **kwargs,
    )


async def embedding_func(texts: list[str]) -> np.ndarray:
    model = _get_model()
    # bge-m3 本地 CPU 编码（同步，串行调用，靠 embedding_func_max_async=1 保证不并发）
    return model.encode(texts, normalize_embeddings=True)


async def main() -> None:
    with open(CORPUS_PATH) as f:
        corpus: list[str] = json.load(f)
    chunks = corpus[:N_CHUNKS]
    print(f"[1/3] 加载 {len(chunks)} 段 corpus（共 {len(corpus)} 段）", flush=True)

    rag = LightRAG(
        working_dir=WORKING_DIR,
        llm_model_func=llm_model_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM,
            max_token_size=8192,
            func=embedding_func,
        ),
        embedding_func_max_async=1,   # 本地 CPU embedding 不并发，避免内存/swap 抖动
        llm_model_max_async=4,        # LLM 走 API，可并发
        max_parallel_insert=3,
    )

    print("初始化 storage...", flush=True)
    await rag.initialize_storages()

    print(f"[2/3] 开始 insert（{len(chunks)} 段，LLM 抽取实体关系）...", flush=True)
    await rag.ainsert(chunks)
    print("insert 完成", flush=True)

    with open(SAMPLE_PATH) as f:
        samples: list[dict] = json.load(f)

    print(f"[3/3] 开始 query（{N_QUERIES} 条 × {len(MODES)} 模式）...", flush=True)
    for si in range(N_QUERIES):
        q = samples[si]["question"]
        gold = samples[si]["answer"]
        print(f"\n{'='*70}\nQ{si}: {q}\nGold answer: {gold}", flush=True)
        for mode in MODES:
            print(f"\n--- mode={mode} ---", flush=True)
            ans = await rag.aquery(q, param=QueryParam(mode=mode))
            print(str(ans)[:600], flush=True)


if __name__ == "__main__":
    asyncio.run(main())

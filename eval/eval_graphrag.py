"""Phase 2c：LightRAG Graph-RAG 评测（方案 B：隔离检索）。

与 2a/2b（eval_golden_corpus.py）的关键区别：
- 检索器 = LightRAG 图检索（local/global/hybrid），不是 dense/hybrid/rerank
- 语料 = golden_corpus 前 200 段（= 前 20 条问题的完整 10 段 context）
- 检索返回 = LightRAG query(only_need_context=True) → 解析 Document Chunks
- 生成 + judge 复用 2a/2b（generate_answer + RAGAS），隔离「检索」这个变量
- 新增 answer_correctness（「是否答对多跳问题」核心指标），gold_recall 暂不评

用法：
    uv run python eval/eval_graphrag.py            # 跑 local+global+hybrid 三模式
    uv run python eval/eval_graphrag.py hybrid     # 只跑 hybrid
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache
from lightrag.utils import EmbeddingFunc
from openai import OpenAI
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import llm_factory
from ragas.metrics import AnswerCorrectness, ContextPrecision, Faithfulness

from enterprise_kb.config import BASE_DIR, get_settings
from enterprise_kb.embed import get_embedding_model
from enterprise_kb.generate import generate_answer
from enterprise_kb.logging import get_logger
from enterprise_kb.rerank import rerank_batch

logger = get_logger(__name__)

CORPUS = BASE_DIR / "data" / "eval" / "golden_corpus.json"
SAMPLE = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"
EVAL_DIR = BASE_DIR / "docs" / "evaluation"
WORKING_DIR = BASE_DIR / ".tmp" / "lightrag_eval_500"

N_CHUNKS = 492        # 前 50 条问题 × context 段（对齐端到端 50 条评测）
N_QUERIES = 50        # 评测前 50 条问题
MODES = ["local", "global", "hybrid"]  # 图检索三模式（不加 naive）

EMBED_DIM = 1024      # bge-m3 dense 维度
RERANK_TOP_K = 3      # LightRAG top-20 → reranker 精排到 top-3（对齐 2b）
MAX_WORKERS = 5
GEN_MODEL = "deepseek/deepseek-flash"
JUDGE_MODEL = "deepseek-chat"
DEEPSEEK_BASE = "https://api.deepseek.com"

OUT_FILES = {
    "local": "phase2c-graphrag-local.md",
    "global": "phase2c-graphrag-global.md",
    "hybrid": "phase2c-graphrag-hybrid.md",
}

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = get_embedding_model()
    return _model


def _deepseek_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    settings = get_settings()
    return settings.deepseek_api_key.get_secret_value() if settings.deepseek_api_key else ""


async def _llm_model_func(prompt, system_prompt=None, history_messages=None, **kwargs):
    return await openai_complete_if_cache(
        "deepseek-chat",
        prompt,
        system_prompt=system_prompt,
        history_messages=history_messages or [],
        api_key=_deepseek_key(),
        base_url=DEEPSEEK_BASE,
        **kwargs,
    )


async def _embedding_func(texts: list[str]) -> np.ndarray:
    return _get_model().encode(texts, normalize_embeddings=True)


def _make_rag() -> LightRAG:
    return LightRAG(
        working_dir=str(WORKING_DIR),
        llm_model_func=_llm_model_func,
        embedding_func=EmbeddingFunc(embedding_dim=EMBED_DIM, max_token_size=8192, func=_embedding_func),
        embedding_func_max_async=1,   # 本地 CPU embedding 不并发，避免内存/swap 抖动
        llm_model_max_async=4,
        max_parallel_insert=3,
    )


# ---------- 解析 only_need_context 返回，提取 Document Chunks ----------

def parse_chunks(ctx_str: str) -> list[str]:
    """从 LightRAG only_need_context 返回里解析「Document Chunks」部分，返回 chunk 文本列表。"""
    idx = ctx_str.find("Document Chunks")
    if idx == -1:
        return []
    json_start = ctx_str.find("```json", idx)
    if json_start == -1:
        return []
    json_end = ctx_str.find("```", json_start + 7)
    if json_end == -1:
        return []
    block = ctx_str[json_start + 7 : json_end]
    chunks: list[str] = []
    for line in block.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        c = obj.get("content", "")
        if c:
            chunks.append(c)
    return chunks


# ---------- 检索（async，LightRAG） ----------

async def _run_retrieval(chunks: list[str], ids: list[str], samples: list[dict]) -> dict[str, list[list[str]]]:
    """索引 200 段 + 三模式检索，返回 {mode: [[chunk...] per question]}。"""
    rag = _make_rag()
    await rag.initialize_storages()
    graphml = WORKING_DIR / "graph_chunk_entity_relation.graphml"
    if graphml.exists():
        logger.info("检测到已有索引，跳过 insert（复用 %s）", graphml)
    else:
        logger.info("开始 insert（%d 段）...", len(chunks))
        await rag.ainsert(chunks, ids=ids)
        logger.info("insert 完成")

    results: dict[str, list[list[str]]] = {m: [] for m in MODES}
    for mode in MODES:
        logger.info("[%s] 检索 %d 条（only_need_context）...", mode, len(samples))
        for s in samples:
            r = await rag.aquery(
                s["question"],
                param=QueryParam(mode=mode, only_need_context=True, enable_rerank=False),
            )
            results[mode].append(parse_chunks(str(r)))
        logger.info("[%s] 检索完成", mode)
    return results


# ---------- 重试 ----------

def _retry(fn, *args, attempts: int = 3, base_delay: float = 2.0, **kwargs):
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            wait = base_delay * (2 ** i)
            logger.warning("调用失败（第 %d/%d 次）err=%s，%.1fs 后重试", i + 1, attempts, e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


# ---------- 生成 + judge ----------

def _generate_one(args):
    question, contexts = args
    result = _retry(generate_answer, question, contexts, model=GEN_MODEL)
    return result.content


def _judge_one(args):
    question, answer, contexts, ground_truth = args
    client = OpenAI(api_key=_deepseek_key(), base_url=DEEPSEEK_BASE)
    llm = llm_factory(JUDGE_MODEL, client=client)

    f_metric = Faithfulness(llm=llm)
    cp_metric = ContextPrecision(llm=llm)
    # weights=[1.0, 0.0]：纯 factual correctness（LLM 判事实），不用 embedding 语义相似度
    ac_metric = AnswerCorrectness(llm=llm, weights=[1.0, 0.0])

    # faithfulness（答案 vs 检索上下文）
    fs = SingleTurnSample(user_input=question, response=answer, retrieved_contexts=contexts)
    f = float(f_metric.single_turn_score(fs))

    # context_precision（检索上下文相关性，需 reference）
    cps = SingleTurnSample(
        user_input=question, response=answer, retrieved_contexts=contexts, reference=ground_truth
    )
    cp = float(cp_metric.single_turn_score(cps))

    # answer_correctness（答案 vs gold answer，核心「是否答对多跳」）
    acs = SingleTurnSample(user_input=question, response=answer, reference=ground_truth)
    ac = float(ac_metric.single_turn_score(acs))

    return f, cp, ac


# ---------- 主流程 ----------

def run_mode(mode: str, samples: list[dict], retrieved: list[list[str]], rerank_k: int | None = None) -> dict:
    # 可选：LightRAG top-20 → bge-reranker 精排 top-k（隔离「精排」这个变量）
    ctxs_list = retrieved
    if rerank_k is not None:
        logger.info("[%s] rerank 精排 top-%d（批量）...", mode, rerank_k)
        questions = [s["question"] for s in samples]
        ctxs_list = rerank_batch(questions, retrieved, rerank_k)

    logger.info("[%s] 生成答案（并发 %d）...", mode, MAX_WORKERS)
    gen_args = [(s["question"], ctxs) for s, ctxs in zip(samples, ctxs_list)]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        answers = list(ex.map(_generate_one, gen_args))

    judge_args = [
        (s["question"], ans, ctxs, s["answer"])
        for s, ans, ctxs in zip(samples, answers, ctxs_list)
    ]
    logger.info("[%s] RAGAS 打分（并发 %d）...", mode, MAX_WORKERS)
    f_scores, cp_scores, ac_scores = [], [], []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_judge_one, a) for a in judge_args]
        for fut in as_completed(futures):
            f, cp, ac = fut.result()
            f_scores.append(f)
            cp_scores.append(cp)
            ac_scores.append(ac)
            done += 1
            if done % 5 == 0:
                logger.info("[%s] judge 进度 %d/%d", mode, done, len(judge_args))

    scores = {
        "answer_correctness": sum(ac_scores) / len(ac_scores),
        "faithfulness": sum(f_scores) / len(f_scores),
        "context_precision": sum(cp_scores) / len(cp_scores),
    }
    logger.info("[%s] 评测完成：%s", mode, scores)

    suffix = "-rerank" if rerank_k is not None else ""
    out = EVAL_DIR / f"phase2c-graphrag-50q-{mode}{suffix}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    rk_desc = (
        f"LightRAG `{mode}` top-20 → bge-reranker-v2-m3 精排 top-{rerank_k}"
        if rerank_k is not None
        else f"LightRAG `{mode}` 模式 top-20（无 rerank）"
    )
    lines = [
        f"# Phase 2c — Graph-RAG（LightRAG）{mode}{suffix.replace('-', ' + ')}",
        "",
        f"- 评测集：HotpotQA distractor 验证集，{len(samples)} 条（前 50 条）",
        f"- 检索库：golden corpus 前 {N_CHUNKS} 段（候选池 {N_CHUNKS}，= 50 条问题的完整 context）",
        f"- 检索：{rk_desc}（only_need_context=True，enable_rerank=False）",
        f"- 生成：{GEN_MODEL}；LLM judge：{JUDGE_MODEL}",
        "",
        f"> 注：2c 是 {N_CHUNKS} 段候选池，与 2a/2b 的 1991 段不可直接比数字，仅看趋势。",
        "",
        "| 指标 | 分数 |",
        "|------|------|",
        f"| answer_correctness | {scores['answer_correctness']:.4f} |",
        f"| faithfulness | {scores['faithfulness']:.4f} |",
        f"| context_precision | {scores['context_precision']:.4f} |",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[%s] 已落盘 %s", mode, out)
    return scores


def main() -> None:
    if not CORPUS.exists():
        raise SystemExit("先运行 python eval/build_golden_corpus.py 生成 golden corpus")
    if not SAMPLE.exists():
        raise SystemExit("缺少评测集 hotpotqa_sample.json")

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))[:N_CHUNKS]
    samples = json.loads(SAMPLE.read_text(encoding="utf-8"))[:N_QUERIES]
    # ids = 段落标题（用于追溯来源）
    ids = [f"{c.split(':', 1)[0]}#{i}" for i, c in enumerate(corpus)]  # title#index 保证唯一
    logger.info("corpus=%d 段，评测集=%d 条", len(corpus), len(samples))

    # 索引 + 检索（async）
    retrieved = asyncio.run(_run_retrieval(corpus, ids, samples))

    mode = sys.argv[1] if len(sys.argv) > 1 else "rerank"
    if mode == "all":
        results = {}
        for m in MODES:
            results[m] = run_mode(m, samples, retrieved[m])
        logger.info("对比结果：%s", results)
    elif mode == "rerank":
        # 只跑 rerank 变体（无 rerank 的 top-20 结果昨晚已落盘）
        results = {}
        for m in MODES:
            results[f"{m}_rerank"] = run_mode(m, samples, retrieved[m], rerank_k=RERANK_TOP_K)
        logger.info("rerank 对比结果：%s", results)
    elif mode in MODES:
        run_mode(mode, samples, retrieved[mode])
    else:
        raise SystemExit(f"未知 mode：{mode}（可选 local/global/hybrid/rerank/all）")


if __name__ == "__main__":
    main()

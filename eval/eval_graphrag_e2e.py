"""Phase 2c 端到端评测：LightRAG 图推理生成答案（only_need_context=False）。

与「隔离检索」（eval_graphrag.py，只取 chunks 喂通用 generate_answer）的关键区别：
- 这里用 LightRAG 自己的 aquery_llm，让它用【实体关系链 + 社区摘要 + chunks】图推理生成答案
- 直接回答「GraphRAG 端到端在多跳问题上到底强不强」——这是之前预期里
  「多跳提升明显」真正对应的对象

评测：
- answer_correctness（核心：答案 vs gold，看多跳答对率）
- faithfulness（答案 vs 它实际用的 data.chunks）
- context_precision（data.chunks vs gold，顺带，预期 ≈ 隔离检索同模式）

用法：
    uv run python eval/eval_graphrag_e2e.py            # 跑 local+global+hybrid
    uv run python eval/eval_graphrag_e2e.py hybrid     # 只跑 hybrid
"""

from __future__ import annotations

import asyncio
import json
import os
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
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

CORPUS = BASE_DIR / "data" / "eval" / "golden_corpus.json"
SAMPLE = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"
EVAL_DIR = BASE_DIR / "docs" / "evaluation"
WORKING_DIR = BASE_DIR / ".tmp" / "lightrag_eval_500"

N_CHUNKS = 492  # 前 50 条评测问题的 context 段总数（对齐 2a/2b 的 50 条）
N_QUERIES = 50
MODES = ["local", "global", "hybrid"]

EMBED_DIM = 1024
MAX_WORKERS = 5
JUDGE_MODEL = "deepseek-chat"
DEEPSEEK_BASE = "https://api.deepseek.com"

OUT_FILES = {
    "local": "phase2c-graphrag-e2e-concise-50q-local.md",
    "global": "phase2c-graphrag-e2e-concise-50q-global.md",
    "hybrid": "phase2c-graphrag-e2e-concise-50q-hybrid.md",
}

# 简洁版 system prompt：替换 LightRAG 默认的「comprehensive + Markdown + References」prompt，
# 让 LLM 只给最终答案，避免答案啰嗦导致 answer_correctness(factuality) 被额外信息稀释。
CONCISE_PROMPT = """---Role---
You are an AI assistant that answers questions using ONLY the provided Context.

---Instructions---
1. Read the Context (Knowledge Graph Data and Document Chunks).
2. Answer the user's query with ONLY the final answer, as briefly as possible.
3. Do NOT mention intermediate entities, reasoning steps, background, or explanations.
4. Do NOT use Markdown (no bold, no headings, no bullet points, no References section).
5. Answer in the same language as the query.
6. If the answer is not in the Context, say "I don't have enough information to answer."

---Context---
{context_data}
"""

# 答案层 gold-recall 判分（0/1，零 embedding）：客观判断「答没答对 gold answer」。
# 用于交叉验证 answer_correctness(factuality) 与 faithfulness 的指标口径问题。
GOLD_RECALL_PROMPT = (
    "Question: {question}\n"
    "Gold (correct) answer: {gold}\n"
    "Predicted answer: {predicted}\n\n"
    "Does the predicted answer correctly answer the question? "
    "Reply with ONLY 'yes' or 'no'."
)

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


E2E_CACHE = WORKING_DIR / "e2e_results_concise.json"


def _make_rag() -> LightRAG:
    return LightRAG(
        working_dir=str(WORKING_DIR),
        llm_model_func=_llm_model_func,
        embedding_func=EmbeddingFunc(embedding_dim=EMBED_DIM, max_token_size=8192, func=_embedding_func),
        embedding_func_max_async=1,
        llm_model_max_async=4,
        max_parallel_insert=3,
        enable_llm_cache=False,
    )


def extract_answer(content: str) -> str:
    """去掉 LightRAG 答案尾部的 ### References 引用块，只留正文。"""
    if not content:
        return ""
    for marker in ("### References", "### 引用", "## References", "\nReferences"):
        idx = content.find(marker)
        if idx != -1:
            return content[:idx].strip()
    return content.strip()


# ---------- 端到端检索 + 生成 ----------

async def _run_e2e(chunks: list[str], ids: list[str], samples: list[dict]) -> dict[str, list[tuple[str, list[str]]]]:
    """端到端：LightRAG 图推理生成答案，返回 {mode: [(answer, ctxs)...]}。"""
    rag = _make_rag()
    await rag.initialize_storages()
    graphml = WORKING_DIR / "graph_chunk_entity_relation.graphml"
    if graphml.exists():
        logger.info("检测到已有索引，跳过 insert（复用 %s）", graphml)
    else:
        logger.info("开始 insert（%d 段）...", len(chunks))
        await rag.ainsert(chunks, ids=ids)
        logger.info("insert 完成")

    results: dict[str, list[tuple[str, list[str]]]] = {m: [] for m in MODES}
    for mode in MODES:
        logger.info("[%s] 端到端查询 %d 条（图推理生成答案）...", mode, len(samples))
        for i, s in enumerate(samples):
            r = await rag.aquery_llm(s["question"], param=QueryParam(mode=mode), system_prompt=CONCISE_PROMPT)
            answer = extract_answer(r.get("llm_response", {}).get("content", ""))
            ctxs = [c.get("content", "") for c in r.get("data", {}).get("chunks", [])]
            results[mode].append((answer, ctxs))
            if (i + 1) % 5 == 0:
                logger.info("[%s] 查询进度 %d/%d", mode, i + 1, len(samples))
        logger.info("[%s] 端到端查询完成", mode)
    # 查询结果落盘缓存（judge 失败时无需重跑查询）
    E2E_CACHE.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    logger.info("端到端查询结果已缓存 %s", E2E_CACHE)
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


# ---------- judge ----------

def _judge_gold_recall(client, question: str, answer: str, gold: str) -> float:
    """0/1 判分：预测答案是否答对了 gold answer（零 embedding，客观）。"""
    prompt = GOLD_RECALL_PROMPT.format(question=question, gold=gold, predicted=answer)
    resp = _retry(
        client.chat.completions.create,
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    text = resp.choices[0].message.content.strip().lower()
    return 1.0 if text.startswith("yes") else 0.0


def _judge_one(args):
    question, answer, contexts, ground_truth = args
    client = OpenAI(api_key=_deepseek_key(), base_url=DEEPSEEK_BASE)
    # 端到端答案比隔离检索长，faithfulness NLI 输出易超默认 max_tokens=1024，提到 4096
    llm = llm_factory(JUDGE_MODEL, client=client, max_tokens=4096)

    f_metric = Faithfulness(llm=llm)
    cp_metric = ContextPrecision(llm=llm)
    ac_metric = AnswerCorrectness(llm=llm, weights=[1.0, 0.0])

    fs = SingleTurnSample(user_input=question, response=answer, retrieved_contexts=contexts)
    f = float(f_metric.single_turn_score(fs))

    cps = SingleTurnSample(
        user_input=question, response=answer, retrieved_contexts=contexts, reference=ground_truth
    )
    cp = float(cp_metric.single_turn_score(cps))

    acs = SingleTurnSample(user_input=question, response=answer, reference=ground_truth)
    ac = float(ac_metric.single_turn_score(acs))

    gr = _judge_gold_recall(client, question, answer, ground_truth)

    return f, cp, ac, gr


# ---------- 主流程 ----------

def run_mode(mode: str, samples: list[dict], e2e: list[tuple[str, list[str]]]) -> dict:
    logger.info("[%s] RAGAS 打分（并发 %d）...", mode, MAX_WORKERS)
    judge_args = [
        (s["question"], ans, ctxs, s["answer"])
        for s, (ans, ctxs) in zip(samples, e2e)
    ]
    f_scores, cp_scores, ac_scores, gr_scores = [], [], [], []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_judge_one, a) for a in judge_args]
        for fut in as_completed(futures):
            f, cp, ac, gr = fut.result()
            f_scores.append(f)
            cp_scores.append(cp)
            ac_scores.append(ac)
            gr_scores.append(gr)
            done += 1
            if done % 5 == 0:
                logger.info("[%s] judge 进度 %d/%d", mode, done, len(judge_args))

    scores = {
        "answer_correctness": sum(ac_scores) / len(ac_scores),
        "faithfulness": sum(f_scores) / len(f_scores),
        "context_precision": sum(cp_scores) / len(cp_scores),
        "gold_recall": sum(gr_scores) / len(gr_scores),
    }
    logger.info("[%s] 评测完成：%s", mode, scores)

    out = EVAL_DIR / OUT_FILES[mode]
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Phase 2c — Graph-RAG 端到端（LightRAG {mode} 图推理，简洁版 prompt）",
        "",
        f"- 评测集：HotpotQA distractor 验证集，{len(samples)} 条（前 50 条）",
        f"- 检索库：golden corpus 前 {N_CHUNKS} 段（候选池 {N_CHUNKS}）",
        f"- 生成：LightRAG `{mode}` 图推理（实体关系链 + 社区摘要 + chunks），only_need_context=False",
        f"- 生成风格：自定义简洁 system_prompt（只给最终答案，无 Markdown/References），enable_llm_cache=False",
        f"- LLM judge：{JUDGE_MODEL}",
        "",
        "> 注：这是「端到端 GraphRAG」（图推理生成答案），区别于「隔离检索」（只取 chunks 喂通用生成器）。",
        "",
        "| 指标 | 分数 |",
        "|------|------|",
        f"| answer_correctness | {scores['answer_correctness']:.4f} |",
        f"| faithfulness | {scores['faithfulness']:.4f} |",
        f"| context_precision | {scores['context_precision']:.4f} |",
        f"| gold_recall | {scores['gold_recall']:.4f} |",
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
    ids = [f"{c.split(':', 1)[0]}#{i}" for i, c in enumerate(corpus)]  # title#index 保证唯一（title 可能重名）
    logger.info("corpus=%d 段，评测集=%d 条", len(corpus), len(samples))

    if E2E_CACHE.exists():
        logger.info("检测到端到端查询缓存，复用 %s", E2E_CACHE)
        e2e = json.loads(E2E_CACHE.read_text(encoding="utf-8"))
    else:
        e2e = asyncio.run(_run_e2e(corpus, ids, samples))

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "all":
        results = {}
        for m in MODES:
            results[m] = run_mode(m, samples, e2e[m])
        logger.info("端到端对比结果：%s", results)
    elif mode in MODES:
        run_mode(mode, samples, e2e[mode])
    else:
        raise SystemExit(f"未知 mode：{mode}（可选 local/global/hybrid/all）")


if __name__ == "__main__":
    main()

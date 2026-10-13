"""M1.6b：RAGAS 评测（支持 naive vs hybrid 检索对比）。

流程：
1. 读 HotpotQA 样本（data/eval/hotpotqa_sample.json，默认 50 条）
2. 每条样本：gold context 摊平成 chunks → 检索（naive 纯 dense / hybrid BM25+dense+RRF）→ 生成答案
3. 逐条用 RAGAS 的 single_turn_score 打分（faithfulness + context_precision），串行 + 进度日志
4. 落盘结果到 docs/evaluation/

用法：
    uv run python eval/eval_ragas.py naive 50     # 纯 dense baseline
    uv run python eval/eval_ragas.py hybrid 50    # 混合检索
    uv run python eval/eval_ragas.py both 50      # 两者都跑

说明：
- 不用 ragas.evaluate（其内部并发 + rate limit 会死锁），改逐条 single_turn_score，可控可追踪
- 生成 LLM 直接指定 deepseek-flash（跳过 claude 无谓 fallback，每条省 ~13s）
- 内存检索（context 段落少 ~10 段），避免为每条样本建 Qdrant 临时 collection
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openai import OpenAI
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import llm_factory
from ragas.metrics import context_precision, faithfulness

from enterprise_kb.config import BASE_DIR, get_settings
from enterprise_kb.embed import encode
from enterprise_kb.generate import generate_answer
from enterprise_kb.hybrid import BM25Retriever, rrf_fusion
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

SAMPLE = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"
EVAL_DIR = BASE_DIR / "docs" / "evaluation"

OUT_FILES = {
    "naive": "phase1-naive-baseline.md",
    "hybrid": "phase2a-hybrid-bm25-rrf.md",
    "hybrid_rerank": "phase2b-hybrid-rerank.md",
}


def load_samples(limit: int = 50) -> list[dict]:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))[:limit]


def flatten_context(context: dict) -> list[str]:
    """把 HotpotQA 的 context（{"title": [...], "sentences": [[...], ...]}）摊平成 chunk 文本。"""
    chunks = []
    for title, sentences in zip(context["title"], context["sentences"]):
        chunks.append(f"{title}: {' '.join(sentences)}")
    return chunks


def _dense_ranked(query: str, chunks: list[str]) -> list[str]:
    """bge-m3 dense 相似度排序（最相关在前）。"""
    query_vec = encode([query])[0]
    chunk_vecs = encode(chunks)
    sims = [sum(a * b for a, b in zip(query_vec, cv)) for cv in chunk_vecs]
    order = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)
    return [chunks[i] for i in order]


def retrieve_naive(query: str, chunks: list[str], top_k: int = 3) -> list[str]:
    """Phase 1：纯 dense 向量 top-k。"""
    return _dense_ranked(query, chunks)[:top_k]


def retrieve_hybrid(query: str, chunks: list[str], top_k: int = 3) -> list[str]:
    """Phase 2a：BM25（sparse）+ dense + RRF 融合。"""
    dense_ranked = _dense_ranked(query, chunks)
    bm25 = BM25Retriever(chunks)
    sparse_ranked = bm25.search(query, k=len(chunks))
    fused = rrf_fusion([dense_ranked, sparse_ranked])
    return fused[:top_k]


def retrieve_hybrid_rerank(query: str, chunks: list[str], top_k: int = 3) -> list[str]:
    """Phase 2b：混合检索取 top-n 候选 → bge-reranker 精排 → top-k。"""
    from enterprise_kb.rerank import rerank as _rerank

    dense_ranked = _dense_ranked(query, chunks)
    bm25 = BM25Retriever(chunks)
    sparse_ranked = bm25.search(query, k=len(chunks))
    fused = rrf_fusion([dense_ranked, sparse_ranked])
    candidates = fused[: get_settings().reranker.top_n]
    return _rerank(query, candidates, top_k)


RETRIEVERS = {
    "naive": retrieve_naive,
    "hybrid": retrieve_hybrid,
    "hybrid_rerank": retrieve_hybrid_rerank,
}


def run_rag(sample: dict, retrieve_fn) -> dict:
    """对一条样本跑 RAG：检索 + 生成（直接 deepseek，跳过 claude fallback）。"""
    chunks = flatten_context(sample["context"])
    contexts = retrieve_fn(sample["question"], chunks)
    result = generate_answer(sample["question"], contexts, model="deepseek/deepseek-flash")
    return {
        "question": sample["question"],
        "answer": result.content,
        "contexts": contexts,
        "ground_truth": sample["answer"],
    }


def _build_judge_llm():
    settings = get_settings()
    key = settings.deepseek_api_key.get_secret_value() if settings.deepseek_api_key else ""
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    return llm_factory("deepseek-chat", client=client)


def score_results(results: list[dict], judge_llm) -> dict:
    """逐条用 RAGAS single_turn_score 打分（串行，进度日志，可追踪卡点）。"""
    faithfulness.llm = judge_llm
    context_precision.llm = judge_llm

    f_scores: list[float] = []
    cp_scores: list[float] = []
    for i, r in enumerate(results, start=1):
        fs = SingleTurnSample(
            user_input=r["question"],
            response=r["answer"],
            retrieved_contexts=r["contexts"],
        )
        f = float(faithfulness.single_turn_score(fs))
        f_scores.append(f)

        cps = SingleTurnSample(
            user_input=r["question"],
            response=r["answer"],
            retrieved_contexts=r["contexts"],
            reference=r["ground_truth"],
        )
        cp = float(context_precision.single_turn_score(cps))
        cp_scores.append(cp)

        logger.info("[%d/%d] faithfulness=%.3f context_precision=%.3f", i, len(results), f, cp)

    return {
        "faithfulness": sum(f_scores) / len(f_scores),
        "context_precision": sum(cp_scores) / len(cp_scores),
    }


def _mode_desc(mode: str) -> str:
    return {
        "naive": "Phase 1 — naive RAG baseline（RAGAS）",
        "hybrid": "Phase 2a — 混合检索 BM25+dense+RRF（RAGAS）",
        "hybrid_rerank": "Phase 2b — 混合检索 + Reranker（RAGAS）",
    }[mode]


def run_mode(mode: str, limit: int) -> dict:
    """跑指定 mode，返回 scores dict。"""
    retrieve_fn = RETRIEVERS[mode]
    samples = load_samples(limit)
    logger.info("[%s] 加载 %d 条样本，开始跑 RAG", mode, len(samples))

    results = [run_rag(s, retrieve_fn) for s in samples]
    logger.info("[%s] 生成完成，开始逐条打分", mode)

    judge_llm = _build_judge_llm()
    scores = score_results(results, judge_llm)
    logger.info("[%s] 评测完成：%s", mode, scores)

    out = EVAL_DIR / OUT_FILES[mode]
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {_mode_desc(mode)}",
        "",
        f"- 评测集：HotpotQA distractor 验证集，{len(results)} 条（固定 50 条，见 README.md）",
    ]
    if mode == "naive":
        lines.append("- 检索：bge-m3 向量 top-3（内存检索）")
    elif mode == "hybrid":
        lines.append("- 检索：BM25（bm25s）+ bge-m3 dense + RRF 融合（k=60），top-3")
    else:
        lines.append("- 检索：BM25 + bge-m3 dense + RRF 融合 → bge-reranker-v2-m3 精排 → top-3")
    lines += [
        "- 生成：deepseek/deepseek-flash",
        "- LLM judge：deepseek-chat",
        "",
        "| 指标 | 分数 |",
        "|------|------|",
    ]
    for name in ["faithfulness", "context_precision"]:
        lines.append(f"| {name} | {scores[name]:.4f} |")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("[%s] 已落盘到 %s", mode, out)
    return scores


def main() -> None:
    if not SAMPLE.exists():
        raise SystemExit("先运行 python eval/build_dataset.py 生成评测样本")

    mode = sys.argv[1] if len(sys.argv) > 1 else "naive"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    if mode == "both":
        naive_scores = run_mode("naive", limit)
        hybrid_scores = run_mode("hybrid", limit)
        logger.info("对比：naive=%s hybrid=%s", naive_scores, hybrid_scores)
    elif mode in RETRIEVERS:
        run_mode(mode, limit)
    else:
        raise SystemExit(f"未知 mode：{mode}（可选 naive/hybrid/both）")


if __name__ == "__main__":
    main()

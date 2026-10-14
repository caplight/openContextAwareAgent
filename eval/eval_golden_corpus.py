"""M2.2：在 golden corpus 上做三路检索评测（naive / hybrid / rerank）。

与旧 eval_ragas.py 的关键区别：
- 检索库 = 共享 golden corpus（~2000 段），而非每条问题自己的 ~10 段 gold context
- corpus dense 向量预计算一次（batch encode），query 向量缓存共享
- 生成 + judge 用受控并发（ThreadPoolExecutor，默认 5）+ 重试退避，避免 rate limit 死锁
- 额外输出 gold evidence recall（supporting_facts 客观指标，零 LLM 成本）

用法：
    uv run python eval/eval_golden_corpus.py both      # naive + hybrid + rerank 都跑
    uv run python eval/eval_golden_corpus.py naive     # 只跑 naive
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from openai import OpenAI
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import llm_factory
from ragas.metrics import ContextPrecision, Faithfulness

from enterprise_kb.config import BASE_DIR, get_settings
from enterprise_kb.embed import get_embedding_model
from enterprise_kb.generate import generate_answer
from enterprise_kb.hybrid import BM25Retriever, rrf_fusion
from enterprise_kb.logging import get_logger
from enterprise_kb.rerank import rerank

logger = get_logger(__name__)

CORPUS = BASE_DIR / "data" / "eval" / "golden_corpus.json"
SAMPLE = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"
EVAL_DIR = BASE_DIR / "docs" / "evaluation"

TOP_K = 3
RERANK_TOP_N = 20
FUSION_CANDIDATE_FACTOR = 4  # 与生产 retrieve.py 一致
MAX_WORKERS = 5
EMBED_BATCH = 16  # 4 核 CPU 上 batch 16 最优（32 会触发 swap 变慢）
GEN_MODEL = "deepseek/deepseek-flash"
JUDGE_MODEL = "deepseek-chat"

OUT_FILES = {
    "naive": "phase1-naive-golden-corpus.md",
    "hybrid": "phase2a-hybrid-golden-corpus.md",
    "hybrid_rerank": "phase2b-hybrid-rerank-golden-corpus.md",
}


# ---------- 检索器 ----------

class GoldenRetriever:
    """预计算 corpus dense 向量 + BM25，三路检索共享 query 向量缓存。"""

    def __init__(self, corpus: list[str]):
        self.corpus = corpus
        self._model = get_embedding_model()
        logger.info("预计算 corpus dense 向量（%d 段，batch_size=%d）...", len(corpus), EMBED_BATCH)
        embs = self._model.encode(corpus, normalize_embeddings=True, batch_size=EMBED_BATCH)
        self.corpus_np = np.asarray(embs, dtype=np.float32)
        logger.info("构建 BM25 索引...")
        self.bm25 = BM25Retriever(corpus)
        self._last_q: str | None = None
        self._last_qv: np.ndarray | None = None

    def _qv(self, query: str) -> np.ndarray:
        if self._last_q == query and self._last_qv is not None:
            return self._last_qv
        self._last_q = query
        self._last_qv = np.asarray(
            self._model.encode([query], normalize_embeddings=True)[0], dtype=np.float32
        )
        return self._last_qv

    def _dense_top(self, qv: np.ndarray, top_n: int) -> list[str]:
        sims = self.corpus_np @ qv
        order = np.argsort(-sims)[:top_n]
        return [self.corpus[i] for i in order]

    def naive(self, query: str) -> list[str]:
        return self._dense_top(self._qv(query), TOP_K)

    def hybrid(self, query: str) -> list[str]:
        qv = self._qv(query)
        n = TOP_K * FUSION_CANDIDATE_FACTOR
        dense = self._dense_top(qv, n)
        sparse = self.bm25.search(query, k=n)
        fused = rrf_fusion([dense, sparse])
        return fused[:TOP_K]

    def hybrid_rerank(self, query: str) -> list[str]:
        qv = self._qv(query)
        dense = self._dense_top(qv, RERANK_TOP_N)
        sparse = self.bm25.search(query, k=RERANK_TOP_N)
        fused = rrf_fusion([dense, sparse])
        candidates = fused[:RERANK_TOP_N]
        return rerank(query, candidates, TOP_K)


RETRIEVERS = {
    "naive": "naive",
    "hybrid": "hybrid",
    "hybrid_rerank": "hybrid_rerank",
}


# ---------- gold evidence recall（客观，零 LLM）----------

def gold_paragraphs(sample: dict) -> set[str]:
    """返回 supporting_facts 标注的 gold 段落文本集合。"""
    sf = sample["supporting_facts"]
    gold: set[str] = set()
    for title in sf.get("title", []):
        for t, sents in zip(sample["context"]["title"], sample["context"]["sentences"]):
            if t == title:
                gold.add(f"{t}: {' '.join(sents)}")
    return gold


def gold_recall_at_k(sample: dict, retrieved: list[str], k: int = TOP_K) -> float | None:
    gold = gold_paragraphs(sample)
    if not gold:
        return None
    hit = sum(1 for p in retrieved[:k] if p in gold)
    return hit / len(gold)


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
    settings = get_settings()
    key = settings.deepseek_api_key.get_secret_value() if settings.deepseek_api_key else ""
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    llm = llm_factory(JUDGE_MODEL, client=client)

    f_metric = Faithfulness(llm=llm)
    cp_metric = ContextPrecision(llm=llm)

    fs = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
    )
    f = float(f_metric.single_turn_score(fs))

    cps = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
        reference=ground_truth,
    )
    cp = float(cp_metric.single_turn_score(cps))
    return f, cp


# ---------- 主流程 ----------

def run_mode(mode: str, samples: list[dict], retriever: GoldenRetriever) -> dict:
    retrieve_fn = getattr(retriever, RETRIEVERS[mode])
    logger.info("[%s] 开始检索（%d 条）", mode, len(samples))

    # 1. 检索（本地，串行快）
    retrieved_list = [retrieve_fn(s["question"]) for s in samples]

    # 2. 生成（受控并发）
    gen_args = [(s["question"], ctxs) for s, ctxs in zip(samples, retrieved_list)]
    logger.info("[%s] 生成答案（并发 %d）...", mode, MAX_WORKERS)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        answers = list(ex.map(_generate_one, gen_args))

    # 3. judge（受控并发，每线程独立 metric 实例）
    judge_args = [
        (s["question"], ans, ctxs, s["answer"])
        for s, ans, ctxs in zip(samples, answers, retrieved_list)
    ]
    logger.info("[%s] RAGAS 打分（并发 %d）...", mode, MAX_WORKERS)
    f_scores: list[float] = []
    cp_scores: list[float] = []
    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_judge_one, a) for a in judge_args]
        for fut in as_completed(futures):
            f, cp = fut.result()
            f_scores.append(f)
            cp_scores.append(cp)
            done += 1
            if done % 10 == 0:
                logger.info("[%s] judge 进度 %d/%d", mode, done, len(judge_args))

    # 4. gold recall（客观）
    recalls = [gold_recall_at_k(s, ctxs) for s, ctxs in zip(samples, retrieved_list)]
    recalls = [r for r in recalls if r is not None]

    scores = {
        "faithfulness": sum(f_scores) / len(f_scores),
        "context_precision": sum(cp_scores) / len(cp_scores),
        "gold_recall@3": sum(recalls) / len(recalls) if recalls else 0.0,
    }
    logger.info("[%s] 评测完成：%s", mode, scores)

    # 5. 落盘
    out = EVAL_DIR / OUT_FILES[mode]
    out.parent.mkdir(parents=True, exist_ok=True)
    desc = {
        "naive": "Phase 1 — naive dense top-3（golden corpus）",
        "hybrid": "Phase 2a — 混合检索 BM25+dense+RRF（golden corpus）",
        "hybrid_rerank": "Phase 2b — 混合检索 + bge-reranker-v2-m3（golden corpus）",
    }[mode]
    lines = [
        f"# {desc}",
        "",
        f"- 评测集：HotpotQA distractor 验证集，{len(samples)} 条（固定 50 条）",
        f"- 检索库：共享 golden corpus，{len(retriever.corpus)} 段（候选池 ~{len(retriever.corpus)}，非每条 10 段）",
        f"- top_k={TOP_K}，reranker top_n={RERANK_TOP_N}，RRF candidate factor={FUSION_CANDIDATE_FACTOR}",
        f"- 生成：{GEN_MODEL}；LLM judge：{JUDGE_MODEL}",
        "",
        "| 指标 | 分数 |",
        "|------|------|",
        f"| faithfulness | {scores['faithfulness']:.4f} |",
        f"| context_precision | {scores['context_precision']:.4f} |",
        f"| gold_recall@3 | {scores['gold_recall@3']:.4f} |",
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

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    samples = json.loads(SAMPLE.read_text(encoding="utf-8"))
    logger.info("golden corpus=%d 段，评测集=%d 条", len(corpus), len(samples))

    retriever = GoldenRetriever(corpus)

    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if mode == "both":
        results = {}
        for m in ["naive", "hybrid", "hybrid_rerank"]:
            results[m] = run_mode(m, samples, retriever)
        logger.info("对比结果：%s", results)
    elif mode in RETRIEVERS:
        run_mode(mode, samples, retriever)
    else:
        raise SystemExit(f"未知 mode：{mode}（可选 naive/hybrid/hybrid_rerank/both）")


if __name__ == "__main__":
    main()

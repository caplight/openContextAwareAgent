"""M1.6b：RAGAS 评测 naive RAG 基线。

流程：
1. 读 HotpotQA 样本（data/eval/hotpotqa_sample.json）
2. 每条样本：把 gold context 段落摊平成 chunks → 内存向量检索（bge-m3）→ 生成答案
3. 收集 (question, answer, contexts, ground_truth)
4. RAGAS 算 faithfulness / context_precision（LLM judge 走 DeepSeek）
5. 落盘 baseline 分数到 docs/evaluation/phase1-naive-baseline.md

说明：
- answer_relevancy 需要额外配置 embeddings，Phase 1 先只算 faithfulness + context_precision
- 内存向量检索（context 段落少，~10 段），避免为每条样本建 Qdrant 临时 collection 的开销
"""

from __future__ import annotations

import json
from pathlib import Path

from datasets import Dataset
from openai import OpenAI
from ragas import evaluate
from ragas.llms import llm_factory
from ragas.metrics import context_precision, faithfulness

from enterprise_kb.config import BASE_DIR, get_settings
from enterprise_kb.embed import encode
from enterprise_kb.generate import generate_answer
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

SAMPLE = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"
OUT = BASE_DIR / "docs" / "evaluation" / "phase1-naive-baseline.md"


def load_samples(limit: int = 20) -> list[dict]:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))[:limit]


def flatten_context(context: dict) -> list[str]:
    """把 HotpotQA 的 context（{"title": [...], "sentences": [[...], ...]}）摊平成 chunk 文本。"""
    chunks = []
    for title, sentences in zip(context["title"], context["sentences"]):
        chunks.append(f"{title}: {' '.join(sentences)}")
    return chunks


def retrieve_from_chunks(query: str, chunks: list[str], top_k: int = 3) -> list[str]:
    """内存向量检索（复用 bge-m3 encode，normalize 后点积即余弦相似度）。"""
    query_vec = encode([query])[0]
    chunk_vecs = encode(chunks)
    sims = [sum(a * b for a, b in zip(query_vec, cv)) for cv in chunk_vecs]
    top_idx = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:top_k]
    return [chunks[i] for i in top_idx]


def run_naive_rag(sample: dict) -> dict:
    """对一条样本跑 naive RAG：检索 + 生成。"""
    chunks = flatten_context(sample["context"])
    contexts = retrieve_from_chunks(sample["question"], chunks)
    result = generate_answer(sample["question"], contexts)
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


def main(limit: int = 20) -> None:
    if not SAMPLE.exists():
        raise SystemExit("先运行 python eval/build_dataset.py 生成评测样本")

    samples = load_samples(limit)
    logger.info("加载 %d 条评测样本，开始跑 naive RAG", len(samples))

    results = [run_naive_rag(s) for s in samples]

    dataset = Dataset.from_dict(
        {
            "question": [r["question"] for r in results],
            "answer": [r["answer"] for r in results],
            "contexts": [r["contexts"] for r in results],
            "ground_truth": [r["ground_truth"] for r in results],
        }
    )

    judge_llm = _build_judge_llm()
    faithfulness.llm = judge_llm
    context_precision.llm = judge_llm
    metrics = [faithfulness, context_precision]

    logger.info("跑 RAGAS 评测（faithfulness + context_precision）")
    result = evaluate(dataset, metrics=metrics)
    df = result.to_pandas()
    # 只取数值列（metric 分数），跳过 user_input/response 等字符串列
    scores = {col: float(df[col].mean()) for col in df.columns if df[col].dtype.kind in "fi"}
    logger.info("评测完成：%s", scores)

    # 落盘
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 1 — naive RAG baseline（RAGAS）",
        "",
        f"- 评测集：HotpotQA distractor 验证集，{len(results)} 条",
        "- 检索：bge-m3 向量 top-3（内存检索）",
        "- 生成：deepseek/deepseek-flash（fallback）",
        "- LLM judge：deepseek-chat",
        "",
        "| 指标 | 分数 |",
        "|------|------|",
    ]
    for name, val in scores.items():
        lines.append(f"| {name} | {val:.4f} |")
    lines.append("")
    lines.append("> 说明：这是 naive RAG 的基线，Phase 2 用混合检索 + rerank + Graph-RAG 后与此对比。")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    logger.info("已落盘 baseline 到 %s", OUT)


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(limit=n)

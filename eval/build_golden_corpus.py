"""M2.1：从 HotpotQA 抽取 golden corpus（档位 2：评测 50 条 + 额外 150 条填充）。

golden corpus = 评测集（data/eval/hotpotqa_sample.json 的 50 条）+ 额外 N 条样本的
context 段落，全部摊平成「title: sentences」文本并去重。

为什么这么做：之前评测每条问题只在「自己 ~10 段 gold context」里检索，候选池太小，
低估了 reranker 价值。把段落合并成共享 golden corpus，候选池放大到 ~2000 段，
更接近真实检索场景，且问题答案（gold 段落）保证在库里。

用法：
    uv run python eval/build_golden_corpus.py 150   # extra=150，共 200 条样本
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from datasets import load_dataset

from enterprise_kb.config import BASE_DIR

SAMPLE = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"
OUT = BASE_DIR / "data" / "eval" / "golden_corpus.json"


def _para(title: str, sentences: list[str]) -> str:
    return f"{title}: {' '.join(sentences)}"


def load_corpus(extra: int = 150) -> list[str]:
    """返回去重后的段落列表（保持插入顺序）。"""
    seen: dict[str, None] = {}

    # 1. 评测集 50 条（固定，保证 gold 段落在库里）
    eval_items = json.loads(SAMPLE.read_text(encoding="utf-8"))
    for item in eval_items:
        for title, sents in zip(item["context"]["title"], item["context"]["sentences"]):
            seen[_para(title, sents)] = None

    n_eval = len(eval_items)

    # 2. 额外样本（validation 第 51 条起，提供干扰段落）
    ds = load_dataset("hotpotqa/hotpot_qa", "distractor", split="validation")
    for i, row in enumerate(ds):
        if i < n_eval:
            continue
        if i >= n_eval + extra:
            break
        for title, sents in zip(row["context"]["title"], row["context"]["sentences"]):
            seen[_para(title, sents)] = None

    return list(seen.keys())


def main(extra: int = 150) -> None:
    corpus = load_corpus(extra)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(corpus, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"golden corpus 落盘：{len(corpus)} 段 → {OUT}")


if __name__ == "__main__":
    extra = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    main(extra=extra)

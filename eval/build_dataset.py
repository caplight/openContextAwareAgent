"""M1.6a：从 HotpotQA 抽取评测集样本（question + answer + gold contexts）。

说明：量化对比（naive vs Graph-RAG）在 HotpotQA 上做（有 ground truth，客观）；
demo 展示用 K8s/AWS Docs（定性）。两者职责分离，见 BLUEPRINT 复盘决策。
"""

from __future__ import annotations

import json

from datasets import load_dataset

from enterprise_kb.config import BASE_DIR

OUT = BASE_DIR / "data" / "eval" / "hotpotqa_sample.json"


def load_sample(limit: int = 50, split: str = "validation") -> list[dict]:
    """加载 HotpotQA distractor 子集，抽取 question/answer/context。

    返回 [{"question", "answer", "context": [{"title", "paragraphs": [...]}]}]
    """
    ds = load_dataset("hotpotqa/hotpot_qa", "distractor", split=split)
    items = []
    for i, row in enumerate(ds):
        if i >= limit:
            break
        # context 是 {"title": str, "sentences": list[str]}
        items.append(
            {
                "question": row["question"],
                "answer": row["answer"],
                "context": row["context"],
                "supporting_facts": row["supporting_facts"],
            }
        )
    return items


def main(limit: int = 50) -> None:
    items = load_sample(limit=limit)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存 {len(items)} 条评测样本到 {OUT}")


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    main(limit=n)

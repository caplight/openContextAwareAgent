"""种子问题生成（评估闭环起点）：从 chunks 提炼概括性问题 + 期望答案。

设计见 `docs/mvp-design.md` §4.1。

流程：上传 PDF → `ingest.load_and_split()` 切分 → 本模块采样 chunk 并批量喂 LLM，
提炼「这条 chunk 能回答什么问题」+ 从原文抽取「期望答案」，供后续评估打分。

关键决策：
- 复用 `llm.generate()`（用户自填生成模型，不内置 judge）
- 批量生成（每批 `_BATCH_SIZE` 个 chunk 一次 LLM 调用，减少调用次数/成本）
- `source_chunk_ids` 记录答案来自哪个 chunk（`ingest._chunk_id` 的稳定 md5 id），
  用于后续 golden case 的召回验证
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from enterprise_kb.llm import generate as _llm_generate
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)

MIN_CHUNK_LEN = 30       # 过滤过短片段（无信息量）
_BATCH_SIZE = 5          # 每批 chunk 数（减少 LLM 调用次数）


class SeedQuestion(BaseModel):
    """一个种子问题：概括性问题 + 期望答案 + 答案来源 chunk id。"""

    question: str
    expected_answer: str
    source_chunk_ids: list[str] = Field(default_factory=list)


_SYSTEM_PROMPT = (
    "你是一个知识库评估问题生成器。"
    "给定若干文档片段，为每个片段生成一个「概括性问题」，并抽取该片段中的「期望答案」。\n"
    "要求：\n"
    "1. 问题是一个真实用户可能问的问题，且能用该片段回答\n"
    "2. 期望答案直接从片段原文抽取，不要改写、不要补充\n"
    "3. 只输出 JSON，不要输出任何其他文字，格式："
    '{"items": [{"index": 0, "question": "...", "answer": "..."}]}\n'
    "   index 是片段在输入中的编号（从 0 开始）"
)


def _sample_chunks(chunks: list[dict], n: int) -> list[dict]:
    """过滤过短片段后均匀采样 n 个（按索引步长，保证覆盖全文档而非局部）。"""
    usable = [c for c in chunks if len(c["text"].strip()) >= MIN_CHUNK_LEN]
    if not usable:
        return []
    if len(usable) <= n:
        return usable
    step = len(usable) / n
    idxs = [int(i * step) for i in range(n)]
    return [usable[i] for i in idxs]


def _build_batch_prompt(batch: list[dict]) -> list[dict]:
    """构造批量生成 prompt（system + 编号 chunk 列表）。"""
    lines = [f"[{i}] {c['text']}" for i, c in enumerate(batch)]
    user = "文档片段（编号从 0 开始）：\n\n" + "\n\n".join(lines)
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _extract_json(text: str) -> dict:
    """从 LLM 返回文本中稳健提取 JSON（容忍 ```json 包裹 / 前后杂质）。"""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"LLM 返回非 JSON: {text[:200]!r}")
    return json.loads(text[start : end + 1])


def generate_seed_questions(
    chunks: list[dict],
    n: int = 25,
    model: str | None = None,
    batch_size: int = _BATCH_SIZE,
) -> list[SeedQuestion]:
    """从 chunks 生成种子问题（批量）。

    Args:
        chunks: `ingest.load_and_split()` 的返回（每个含 id/text/meta）。
        n: 目标种子问题数（20–30 之间）。
        model: 显式指定生成模型（None 走全局 primary）。

    Returns:
        种子问题列表（实际数量可能 < n，因 LLM 可能漏掉部分 chunk）。
    """
    sampled = _sample_chunks(chunks, n)
    if not sampled:
        logger.warning("无可用 chunk（全部过短），跳过种子问题生成")
        return []

    out: list[SeedQuestion] = []
    for i in range(0, len(sampled), batch_size):
        batch = sampled[i : i + batch_size]
        result = _llm_generate(_build_batch_prompt(batch), model=model)
        try:
            data = _extract_json(result.content)
            items = data.get("items", [])
            if not isinstance(items, list):
                logger.warning("items 字段非列表，跳过该批: %r", items)
                continue
        except (ValueError, json.JSONDecodeError) as e:  # noqa: BLE001
            logger.warning("解析种子问题失败，跳过该批: %s", e)
            continue

        for item in items:
            try:
                idx = int(item["index"])
                chunk = batch[idx]
                out.append(
                    SeedQuestion(
                        question=item["question"].strip(),
                        expected_answer=item["answer"].strip(),
                        source_chunk_ids=[chunk["id"]],
                    )
                )
            except (KeyError, IndexError, ValueError, TypeError):
                logger.warning("跳过无效 item: %r", item)

    logger.info("生成 %d 个种子问题（采样 %d 个 chunk）", len(out), len(sampled))
    return out

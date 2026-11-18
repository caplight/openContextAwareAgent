"""用户 listwise 评分 + 置信度（评估闭环的主观反馈层）。

设计见 `docs/mvp-design.md` §4.3。

借鉴 Pistis-RAG：listwise 而非逐 chunk（低摩擦，用户对「整份结果」表态，
不逐条打详细评语）。
置信度借鉴 ARES PPI 思路：少量评分 → 置信区间，而非裸分。
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

RatingValue = Literal["up", "down", "copied", "regenerated"]

# 正面信号：up（点赞）+ copied（复制，暗示有用）
_POSITIVE: set[str] = {"up", "copied"}


class Rating(BaseModel):
    """一条用户评分（listwise，低摩擦）。"""

    question: str
    rating: RatingValue


def positive_rate(ratings: list[Rating]) -> float:
    """正面评分占比（up + copied 视为正面）。空列表返回 0.0。"""
    if not ratings:
        return 0.0
    return sum(1 for r in ratings if r.rating in _POSITIVE) / len(ratings)


def compute_confidence(ratings: list[Rating]) -> float:
    """基于样本量的置信度（sigmoid 型，ARES PPI 思路简化）。

    样本越多置信度越高，但永远不到 1（诚实：不确定）。
    - n=0  → 0.0
    - n=5  → ~0.34
    - n=12 → ~0.63
    - n=25 → ~0.88
    """
    n = len(ratings)
    if n <= 0:
        return 0.0
    return 1 - math.exp(-n / 12)

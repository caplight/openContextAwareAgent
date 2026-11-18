"""可解释建议（核心壁垒）：把「不同参数值的评估分数」翻译成「人话建议 + 置信度」。

设计见 `docs/mvp-design.md` §4.4 + §5。

核心：
- Greedy-M 贪心（模型优先），MVP 只做 `top_k` 一个参数（连续参数 → weak 建议）
- 诚实性红线：不硬编码最优参数表，一切基于真实评估分数（见 `product-design.md` §4.2）
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from enterprise_kb.rating import Rating, compute_confidence

# 提升低于该阈值不建议（避免把评估噪音当成「值得调」）
_IMPROVEMENT_THRESHOLD = 0.05


class Suggestion(BaseModel):
    """一条可解释建议。"""

    param: str                       # 要调的参数（MVP 固定 "top_k"）
    current: int                     # 当前值
    recommended: int                 # 建议值
    reason: str                      # 人话理由（为什么）
    confidence: float                # 置信度（0~1，基于样本量）
    category: Literal["strong", "weak"] = "weak"


def suggest_top_k(
    current: int,
    scores: dict[int, float],
    ratings: list[Rating] | None = None,
) -> Suggestion | None:
    """对比不同 top_k 的评估分数，输出可解释建议。

    Args:
        current: 当前 top_k。
        scores: `{top_k: avg_faithfulness}`（不同 top_k 的评估分数）。
        ratings: 用户评分（用于置信度样本量）。

    Returns:
        `Suggestion`（建议调到最优 top_k），或 `None`（无需调整 / 数据不足）。
    """
    if not scores:
        return None

    best_k = max(scores, key=scores.get)
    best_score = scores[best_k]
    cur_score = scores.get(current)

    # 当前值已是候选里最优 → 不调
    if best_k == current:
        return None
    # 提升不显著（低于阈值）→ 不调，避免噪音
    if cur_score is not None and best_score - cur_score < _IMPROVEMENT_THRESHOLD:
        return None

    confidence = compute_confidence(ratings or [])

    if cur_score is not None:
        reason = (
            f"试了几组后 top_k={best_k} 的忠实度明显更高"
            f"（{best_score:.2f} vs {cur_score:.2f}），建议上调"
        )
    else:
        reason = f"top_k={best_k} 的忠实度最高（{best_score:.2f}），建议采用"

    return Suggestion(
        param="top_k",
        current=current,
        recommended=best_k,
        reason=reason,
        confidence=confidence,
        category="weak",
    )

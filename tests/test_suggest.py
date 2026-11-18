"""suggest 测试：可解释建议逻辑（对比不同 top_k 评估分数）。"""

from __future__ import annotations

from enterprise_kb.rating import Rating
from enterprise_kb.suggest import Suggestion, suggest_top_k


def _ratings(n: int) -> list[Rating]:
    return [Rating(question=f"q{i}", rating="up") for i in range(n)]


def test_no_scores_returns_none():
    assert suggest_top_k(5, {}) is None


def test_current_already_best_returns_none():
    scores = {3: 0.6, 5: 0.8, 8: 0.7}
    assert suggest_top_k(5, scores) is None


def test_improvement_below_threshold_returns_none():
    # 8 比 5 高 0.02（< 0.05 阈值）→ 不调
    scores = {5: 0.80, 8: 0.82}
    assert suggest_top_k(5, scores) is None


def test_improvement_significant_suggests():
    scores = {5: 0.71, 8: 0.82}  # 提升 0.11 > 0.05
    s = suggest_top_k(5, scores, ratings=_ratings(12))
    assert isinstance(s, Suggestion)
    assert s.param == "top_k"
    assert s.current == 5
    assert s.recommended == 8
    assert s.category == "weak"
    assert "0.82" in s.reason and "0.71" in s.reason
    assert s.confidence > 0.5  # 12 条评分 → 置信度 ~0.63


def test_current_not_in_scores():
    # 当前 top_k=5 没测过，仍可建议（reason 用绝对值描述）
    scores = {3: 0.6, 8: 0.8}
    s = suggest_top_k(5, scores)
    assert s is not None
    assert s.recommended == 8
    assert s.current == 5


def test_confidence_reflects_ratings():
    scores = {5: 0.71, 8: 0.82}
    low = suggest_top_k(5, scores, ratings=_ratings(2))
    high = suggest_top_k(5, scores, ratings=_ratings(25))
    assert low.confidence < high.confidence
    assert suggest_top_k(5, scores, ratings=None).confidence == 0.0


def test_recommends_best_k():
    scores = {3: 0.5, 5: 0.71, 8: 0.82, 10: 0.75}
    s = suggest_top_k(5, scores)
    assert s.recommended == 8  # 最高分

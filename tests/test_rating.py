"""rating 测试：Rating 模型 + positive_rate + compute_confidence。"""

from __future__ import annotations

import pytest

from enterprise_kb.rating import Rating, compute_confidence, positive_rate


def _rs(*vals):
    return [Rating(question=f"q{i}", rating=v) for i, v in enumerate(vals)]


def test_positive_rate_empty():
    assert positive_rate([]) == 0.0


def test_positive_rate_mixed():
    rs = _rs("up", "down", "copied", "regenerated")
    # up + copied = 2 正面 / 4 总数 = 0.5
    assert positive_rate(rs) == 0.5


def test_positive_rate_all_positive():
    rs = _rs("up", "copied", "up")
    assert positive_rate(rs) == 1.0


def test_confidence_zero():
    assert compute_confidence([]) == 0.0


def test_confidence_increases_with_n():
    c5 = compute_confidence(_rs("up") * 5)
    c12 = compute_confidence(_rs("up") * 12)
    c25 = compute_confidence(_rs("up") * 25)
    assert 0.0 < c5 < c12 < c25 < 1.0


def test_confidence_approx_values():
    # 1 - exp(-12/12) = 1 - exp(-1) ≈ 0.632
    assert compute_confidence(_rs("up") * 12) == pytest.approx(0.632, abs=0.01)
    # 1 - exp(-25/12) ≈ 0.875
    assert compute_confidence(_rs("up") * 25) == pytest.approx(0.875, abs=0.01)

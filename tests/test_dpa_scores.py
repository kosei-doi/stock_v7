"""dpa_scores のユニットテスト。"""
from __future__ import annotations

import pytest

from core.dpa.dpa_scores import compute_score_trend


def _history_from_scores(ticker: str, scores: list[float]) -> dict:
    history: dict = {}
    for i, s in enumerate(scores, start=1):
        date_key = f"2026-01-{i:02d}"
        history[date_key] = {ticker: {"total": float(s)}}
    return history


def test_compute_score_trend_uses_linear_regression_slope():
    # 1日あたり +2 の線形上昇: slope=2 -> trend=2/5=0.4
    h = _history_from_scores("AAA", [10, 12, 14, 16, 18])
    out = compute_score_trend("AAA", h, max_points=10, slope_scale=5.0)
    assert out["last"] == pytest.approx(18.0)
    assert out["level"] == pytest.approx(0.18)
    assert out["trend"] == pytest.approx(0.4, abs=1e-6)


def test_compute_score_trend_returns_zero_when_less_than_three_points():
    h = _history_from_scores("AAA", [50, 52])
    out = compute_score_trend("AAA", h, max_points=10, slope_scale=5.0)
    assert out["trend"] == 0.0


def test_compute_score_trend_is_clipped_to_unit_range():
    # 1日あたり +10 の上昇: slope/5 = 2.0 -> +1.0 にクリップ
    h = _history_from_scores("AAA", [10, 20, 30, 40, 50])
    out = compute_score_trend("AAA", h, max_points=10, slope_scale=5.0)
    assert out["trend"] == 1.0

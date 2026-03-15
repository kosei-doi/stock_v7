"""dpa_portfolio_score のユニットテスト。"""
from __future__ import annotations

import pytest
from core.dpa.dpa_schema import MacroState
from core.dpa.dpa_portfolio_score import get_defense_intensity, compute_portfolio_total_score
from core.dvc.schema import DvcScoreOutput, Scores, MarketLinkage, RiskMetrics, AiAnalysis


def _make_output(
    total_score: float,
    beta: float | None = None,
    r_squared: float | None = None,
    alpha: float | None = None,
    atr_percent: float | None = None,
) -> DvcScoreOutput:
    return DvcScoreOutput(
        ticker="7203.T",
        name="Toyota",
        sector="Consumer Cyclical",
        scores=Scores(
            value_score=50.0,
            safety_score=50.0,
            momentum_score=50.0,
            total_score=total_score,
        ),
        market_linkage=MarketLinkage(
            benchmark="1306.T",
            beta=beta,
            r_squared=r_squared,
            alpha=alpha,
        ),
        risk_metrics=RiskMetrics(atr_percent=atr_percent),
        ai_analysis=AiAnalysis(
            catalyst_summary=None,
            stop_loss_recommendation=None,
            warning_flag=None,
        ),
        data_overview=None,
    )


def test_get_defense_intensity():
    # 0.4 以下 -> 0
    s = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.3, vi_z=None, macd_trend=None)
    assert get_defense_intensity(s) == 0.0
    # 0.8 以上 -> 1
    s = MacroState(phase="panic", phase_name_ja="パニック", target_cash_ratio=0.8, vi_z=None, macd_trend=None)
    assert get_defense_intensity(s) == 1.0
    # 0.6 -> 0.5
    s = MacroState(phase="caution", phase_name_ja="警戒", target_cash_ratio=0.6, vi_z=None, macd_trend=None)
    assert get_defense_intensity(s) == pytest.approx(0.5)


def test_compute_portfolio_total_score_base_only():
    d = _make_output(total_score=70.0, beta=None, r_squared=None, alpha=None, atr_percent=None)
    macro = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.3, vi_z=None, macd_trend=None)
    score = compute_portfolio_total_score(d, macro)
    assert score == pytest.approx(70.0)


def test_compute_portfolio_total_score_high_beta_penalized():
    d = _make_output(total_score=70.0, beta=1.5, r_squared=0.5, alpha=0.0, atr_percent=2.0)
    macro_low = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.3, vi_z=None, macd_trend=None)
    macro_high = MacroState(phase="panic", phase_name_ja="パニック", target_cash_ratio=0.8, vi_z=None, macd_trend=None)
    score_low = compute_portfolio_total_score(d, macro_low)
    score_high = compute_portfolio_total_score(d, macro_high)
    assert score_high < score_low


def test_compute_portfolio_total_score_positive_alpha_boost():
    d = _make_output(total_score=60.0, beta=1.0, r_squared=0.3, alpha=0.0005, atr_percent=1.0)
    macro = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.3, vi_z=None, macd_trend=None)
    score = compute_portfolio_total_score(d, macro)
    assert score > 60.0

"""dpa_weights のユニットテスト。"""
from __future__ import annotations

import pytest
from core.dpa.dpa_schema import MacroState
from core.dpa.dpa_weights import compute_target_weights
from core.dvc.schema import DvcScoreOutput, Scores, MarketLinkage, RiskMetrics, AiAnalysis


def _make_output(ticker: str, total_score: float = 50.0) -> DvcScoreOutput:
    return DvcScoreOutput(
        ticker=ticker,
        name=ticker,
        sector=None,
        scores=Scores(value_score=50, safety_score=50, momentum_score=50, total_score=total_score),
        market_linkage=MarketLinkage(benchmark="1306.T", beta=1.0, r_squared=0.5, alpha=0.0),
        risk_metrics=RiskMetrics(atr_percent=2.0),
        ai_analysis=AiAnalysis(catalyst_summary=None, stop_loss_recommendation=None, warning_flag=None),
        data_overview=None,
    )


def test_compute_target_weights_normalizes_to_non_cash():
    dvc_results = {
        "A": _make_output("A", 80.0),
        "B": _make_output("B", 60.0),
    }
    score_trends = {
        "A": {"level": 0.8, "trend": 0.2},
        "B": {"level": 0.6, "trend": 0.0},
    }
    macro = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.2, vi_z=None, macd_trend=None)
    weights = compute_target_weights(dvc_results, score_trends, macro, portfolio_scores={"A": 80.0, "B": 60.0})
    assert set(weights.keys()) == {"A", "B"}
    total = sum(weights.values())
    assert total == pytest.approx(0.8)  # 1 - 0.2 cash
    assert weights["A"] > weights["B"]


def test_compute_target_weights_high_cash_ratio():
    dvc_results = {"A": _make_output("A", 70.0)}
    score_trends = {"A": {"level": 0.7, "trend": 0.0}}
    macro = MacroState(phase="panic", phase_name_ja="パニック", target_cash_ratio=0.8, vi_z=None, macd_trend=None)
    weights = compute_target_weights(dvc_results, score_trends, macro, portfolio_scores={"A": 70.0})
    assert sum(weights.values()) == pytest.approx(0.2)


def test_compute_target_weights_empty_trends_skipped():
    dvc_results = {"A": _make_output("A", 70.0)}
    score_trends = {"A": {"level": None, "trend": None}}
    macro = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.3, vi_z=None, macd_trend=None)
    # portfolio_scores があれば level はそれで上書きされるので、level=None でも 0.7/100 で level がつく
    weights = compute_target_weights(dvc_results, score_trends, macro, portfolio_scores={"A": 70.0})
    assert "A" in weights


def test_compute_target_weights_allocation_holdings_only():
    """保有銘柄集合だけで non_cash を山分けし、それ以外は 0。"""
    dvc_results = {
        "A": _make_output("A", 80.0),
        "B": _make_output("B", 60.0),
        "C": _make_output("C", 90.0),
    }
    score_trends = {
        "A": {"level": 0.8, "trend": 0.2},
        "B": {"level": 0.6, "trend": 0.0},
        "C": {"level": 0.9, "trend": 0.0},
    }
    macro = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.2, vi_z=None, macd_trend=None)
    ps = {"A": 80.0, "B": 60.0, "C": 90.0}
    # A, B のみ保有想定 → raw は A,B だけで正規化、合計 non_cash=0.8
    w = compute_target_weights(
        dvc_results, score_trends, macro, portfolio_scores=ps, allocation_tickers={"A", "B"}
    )
    assert w.get("C", 0) == 0.0
    assert w["A"] + w["B"] == pytest.approx(0.8)
    assert w["A"] > w["B"]


def test_compute_target_weights_uses_trend_globally():
    """trend は常に有効。level が同じなら trend が高い銘柄の重みが増える。"""
    dvc_results = {
        "A": _make_output("A", 80.0),
        "B": _make_output("B", 80.0),
    }
    score_trends = {
        "A": {"level": 0.8, "trend": 1.0},
        "B": {"level": 0.8, "trend": -1.0},
    }
    macro = MacroState(phase="cruise", phase_name_ja="巡航", target_cash_ratio=0.2, vi_z=None, macd_trend=None)
    w = compute_target_weights(
        dvc_results,
        score_trends,
        macro,
        portfolio_scores={"A": 80.0, "B": 80.0},
    )
    assert w["A"] > w["B"]

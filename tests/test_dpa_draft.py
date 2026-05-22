"""dpa_draft のユニットテスト（既存保有の増分購入）。"""
from __future__ import annotations

from core.dpa.dpa_draft import run_draft
from core.dpa.dpa_schema import MacroPhase, MacroState
from core.dvc.schema import AiAnalysis, DvcScoreOutput, MarketLinkage, RiskMetrics, Scores


def _make_output(ticker: str, momentum: float = 60.0, total_score: float = 80.0) -> DvcScoreOutput:
    return DvcScoreOutput(
        ticker=ticker,
        name=ticker,
        sector=None,
        scores=Scores(
            value_score=50,
            safety_score=50,
            momentum_score=momentum,
            total_score=total_score,
        ),
        market_linkage=MarketLinkage(benchmark="1306.T", beta=1.0, r_squared=0.5, alpha=0.0),
        risk_metrics=RiskMetrics(atr_percent=2.0),
        ai_analysis=AiAnalysis(
            catalyst_summary=None,
            stop_loss_recommendation=None,
            warning_flag=None,
        ),
        data_overview=None,
    )


def test_run_draft_skips_incremental_buy_when_holding_at_target():
    """既存保有の評価額が目標以上なら、その銘柄への追加買いは出ない。"""
    ticker = "AAA"
    price = 1000.0
    total_capital = 1_000_000.0
    # 800 株 × 1000 円 = 80 万円。非現金配分がおおむね 75 万円以下なら増分ゼロ。
    holdings = [{"ticker": ticker, "shares": 800}]
    snapshot = _make_output(ticker, momentum=60.0, total_score=80.0)
    macro = MacroState(
        phase=MacroPhase.CRUISE,
        phase_name_ja="巡航",
        target_cash_ratio=0.25,
        vi_z=None,
        macd_trend=None,
    )
    all_scores = {ticker: snapshot}
    portfolio_scores = {ticker: 80.0}
    score_trends = {ticker: {"level": 0.8, "trend": 0.1}}

    out = run_draft(
        available_budget=500_000.0,
        total_capital_actual=total_capital,
        macro_state=macro,
        holdings=holdings,
        watching_snapshots=[snapshot],
        current_prices={ticker: price},
        target_weights={},
        current_weights={ticker: 0.8},
        score_trends=score_trends,
        portfolio_scores=portfolio_scores,
        all_scores=all_scores,
        momentum_threshold=50.0,
        lot_size=100,
        max_position_pct=0.15,
        max_position_jpy=750_000.0,
    )

    tickers_in_recs = {r.ticker for r in out.recommendations}
    assert ticker not in tickers_in_recs


def test_run_draft_near_zero_incremental_below_one_lot():
    """増分が 1 ロット未満なら購入推奨に含めない。"""
    ticker = "BBB"
    price = 1000.0
    total_capital = 1_000_000.0
    # 目標 ≒75 万、保有 70 万 → 増分 5 万 < 1 ロット(10 万)
    holdings = [{"ticker": ticker, "shares": 700}]
    snapshot = _make_output(ticker, momentum=55.0, total_score=75.0)
    macro = MacroState(
        phase=MacroPhase.CRUISE,
        phase_name_ja="巡航",
        target_cash_ratio=0.25,
        vi_z=None,
        macd_trend=None,
    )
    all_scores = {ticker: snapshot}
    portfolio_scores = {ticker: 75.0}
    score_trends = {ticker: {"level": 0.75, "trend": 0.0}}

    out = run_draft(
        available_budget=500_000.0,
        total_capital_actual=total_capital,
        macro_state=macro,
        holdings=holdings,
        watching_snapshots=[snapshot],
        current_prices={ticker: price},
        target_weights={},
        current_weights={ticker: 0.7},
        score_trends=score_trends,
        portfolio_scores=portfolio_scores,
        all_scores=all_scores,
        momentum_threshold=50.0,
        lot_size=100,
        max_position_pct=0.15,
        max_position_jpy=750_000.0,
    )

    assert all(r.ticker != ticker for r in out.recommendations)

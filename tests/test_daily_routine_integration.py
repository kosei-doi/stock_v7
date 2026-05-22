"""daily_routine の統合テスト（DVC・マクロ取得はモック、purge→draft 予算連鎖）。"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from core.dpa.dpa_schema import MacroPhase, MacroState
from core.dvc.schema import (
    AiAnalysis,
    DataOverview,
    DvcScoreOutput,
    MarketLinkage,
    PriceHistoryOverview,
    RiskMetrics,
    Scores,
)
from core.utils.money import yen_floor

HOLDING_TICKER = "HOLDING.T"
WATCH_TICKER = "WATCH.T"
PRICE = 1000.0


def _make_dvc_output(
    ticker: str,
    *,
    momentum: float = 60.0,
    total_score: float = 80.0,
    last_close: float = PRICE,
) -> DvcScoreOutput:
    return DvcScoreOutput(
        ticker=ticker,
        name=ticker.replace(".T", ""),
        sector="Technology",
        scores=Scores(
            value_score=50.0,
            safety_score=50.0,
            momentum_score=momentum,
            total_score=total_score,
        ),
        market_linkage=MarketLinkage(
            benchmark="1306.T",
            beta=1.0,
            r_squared=0.5,
            alpha=0.0,
        ),
        risk_metrics=RiskMetrics(atr_percent=2.0),
        ai_analysis=AiAnalysis(
            catalyst_summary=None,
            stop_loss_recommendation=None,
            warning_flag=None,
        ),
        data_overview=DataOverview(
            price_history=PriceHistoryOverview(
                rows=100,
                date_min="2024-01-01",
                date_max="2025-01-01",
                columns=["close"],
                last_close=last_close,
                empty=False,
            ),
        ),
    )


def _mock_dvc_results() -> dict[str, DvcScoreOutput]:
    return {
        HOLDING_TICKER: _make_dvc_output(
            HOLDING_TICKER, momentum=30.0, total_score=40.0
        ),
        WATCH_TICKER: _make_dvc_output(
            WATCH_TICKER, momentum=70.0, total_score=90.0
        ),
    }


def _mock_macro_data():
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    rng = np.random.default_rng(42)
    close = pd.Series(100.0 + np.cumsum(rng.normal(0, 0.3, size=len(dates))), index=dates)
    bench_df = pd.DataFrame({"close": close})
    vi_series = pd.Series(np.linspace(18.0, 20.0, 61))
    peers_data = {"Technology": [HOLDING_TICKER, WATCH_TICKER]}
    return bench_df, peers_data, vi_series


@pytest.fixture
def routine_env(tmp_path, monkeypatch):
    """run_daily_routine 用の一時ファイルと外部依存モック。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    watchlist = [
        {"ticker": HOLDING_TICKER, "status": "HOLDING", "shares": 800},
        {"ticker": WATCH_TICKER, "status": "WATCHING"},
    ]
    (data_dir / "watchlist.json").write_text(
        json.dumps(watchlist), encoding="utf-8"
    )
    (tmp_path / "portfolio_state.json").write_text(
        json.dumps({"cash_yen": 200_000}), encoding="utf-8"
    )
    (data_dir / "sector_peers.json").write_text(
        json.dumps({"Technology": [HOLDING_TICKER, WATCH_TICKER]}),
        encoding="utf-8",
    )
    (data_dir / "daily_cache.json").write_text("{}", encoding="utf-8")
    (data_dir / "scores_history.json").write_text("{}", encoding="utf-8")

    import daily_routine as dr

    monkeypatch.setattr(dr, "run_dvc_for_watchlist", lambda **_kw: _mock_dvc_results())
    monkeypatch.setattr(dr, "get_macro_and_peers_data", lambda **_kw: _mock_macro_data())

    paths = {
        "watchlist_path": str(data_dir / "watchlist.json"),
        "sector_peers_path": str(data_dir / "sector_peers.json"),
        "portfolio_path": str(tmp_path / "portfolio_state.json"),
        "cache_path": str(data_dir / "daily_cache.json"),
        "output_dir": str(output_dir),
        "scores_history_path": str(data_dir / "scores_history.json"),
    }
    return dr, paths


def test_run_daily_routine_smoke(routine_env):
    """日次ルーチンが最後まで完了しレポート主要フィールドを返す。"""
    dr, paths = routine_env
    report = dr.run_daily_routine(verbose=False, **paths)

    assert report.data_date
    assert report.phase is not None
    assert report.cash_yen is not None
    assert report.total_capital_yen is not None
    assert report.purge is not None
    assert report.draft is not None
    assert report.report_text


def test_purge_to_draft_budget_chain(routine_env):
    """purge 見込み現金が raw_available_budget → draft_budget_cap に連鎖する。"""
    dr, paths = routine_env
    report = dr.run_daily_routine(verbose=False, **paths)

    cash = int(report.cash_yen or 0)
    total_cap = int(report.total_capital_yen or 0)
    est_cash = int(report.purge.estimated_cash_generated)
    ratio = float(report.target_cash_ratio)

    assert est_cash > 0, "オーバーウェイト保有で売却見込み現金が出る想定"
    assert report.phase != MacroPhase.PANIC

    expected_raw = yen_floor(max(0.0, cash + est_cash - total_cap * ratio))
    assert report.draft.raw_available_budget == expected_raw
    assert report.draft.draft_budget_cap == expected_raw
    assert report.draft.available_budget <= report.draft.draft_budget_cap


def test_run_daily_routine_panic_zero_draft_cap(routine_env, monkeypatch):
    """PANIC 時はドラフト予算上限 0・購入推奨なし。"""
    dr, paths = routine_env

    panic_macro = MacroState(
        phase=MacroPhase.PANIC,
        phase_name_ja="パニック",
        target_cash_ratio=0.75,
        vi_z=3.0,
        macd_trend=-0.5,
    )
    monkeypatch.setattr(dr, "get_macro_state", lambda *_a, **_kw: panic_macro)

    report = dr.run_daily_routine(verbose=False, **paths)

    assert report.phase == MacroPhase.PANIC
    assert report.draft.draft_budget_cap == 0
    assert report.draft.available_budget == 0
    assert len(report.draft.recommendations) == 0

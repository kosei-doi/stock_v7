"""dpa_purge のユニットテスト。"""
from __future__ import annotations

from core.dpa.dpa_purge import run_purge
from core.dpa.dpa_schema import MacroPhase


def test_run_purge_rounds_up_by_lot_threshold():
    # excess_value=1.55 lot 分 -> threshold=0.5 なら 2 lot 売却
    out = run_purge(
        phase=MacroPhase.CAUTION,
        holdings=[{"ticker": "AAA", "shares": 200}],
        current_weights={"AAA": 0.20},
        target_weights={"AAA": 0.045},
        current_prices={"AAA": 10.0},
        total_capital_actual=10_000.0,  # target_value=450, position=2000, excess=1550
        over_weight_threshold=0.02,
        lot_size=100,
        purge_lot_threshold=0.5,
    )
    assert out.total_count == 1
    assert out.items[0].shares_to_sell == 200


def test_run_purge_no_round_up_when_remainder_below_threshold():
    # 同じ excess=1.55 lot でも threshold=0.8 なら 1 lot 売却
    out = run_purge(
        phase=MacroPhase.CAUTION,
        holdings=[{"ticker": "AAA", "shares": 200}],
        current_weights={"AAA": 0.20},
        target_weights={"AAA": 0.045},
        current_prices={"AAA": 10.0},
        total_capital_actual=10_000.0,
        over_weight_threshold=0.02,
        lot_size=100,
        purge_lot_threshold=0.8,
    )
    assert out.total_count == 1
    assert out.items[0].shares_to_sell == 100

"""dpa_purge のユニットテスト。"""
from __future__ import annotations

import pytest

from core.dpa.dpa_purge import run_purge
from core.dpa.dpa_schema import MacroPhase


def _base_inputs():
    holdings = [{"ticker": "AAA", "shares": 300}]
    target_weights = {"AAA": 0.10}
    current_prices = {"AAA": 1000.0}
    total_capital_actual = 1_000_000.0
    return holdings, target_weights, current_prices, total_capital_actual


def test_run_purge_asymmetric_rounding_rounds_up_when_remainder_over_threshold():
    holdings, target_weights, current_prices, total_capital_actual = _base_inputs()
    # excess_value = 300k - 100k = 200k, lot_cost=100k -> 2.0 lots なので基準ケース
    out = run_purge(
        phase=MacroPhase.CAUTION,
        holdings=holdings,
        target_weights=target_weights,
        current_prices=current_prices,
        total_capital_actual=total_capital_actual,
        lot_size=100,
        purge_lot_threshold=0.5,
    )
    assert out.total_count == 1
    assert out.items[0].shares_to_sell == 200
    assert out.items[0].estimated_sale_cash == pytest.approx(200_000.0)


def test_run_purge_asymmetric_rounding_changes_decision_at_threshold():
    holdings = [{"ticker": "AAA", "shares": 100}]
    target_weights = {"AAA": 0.0}
    current_prices = {"AAA": 1000.0}
    total_capital_actual = 625_000.0  # excess=100k, lot_cost=100k -> 1 lot

    # このケースを使って 0.49 lot 相当を作る
    target_weights = {"AAA": (100_000.0 - 49_000.0) / total_capital_actual}
    # excess=49,000 -> fractional_lots=0.49
    out_no_round_up = run_purge(
        phase=MacroPhase.CRUISE,
        holdings=holdings,
        target_weights=target_weights,
        current_prices=current_prices,
        total_capital_actual=total_capital_actual,
        lot_size=100,
        purge_lot_threshold=0.5,
    )
    assert out_no_round_up.total_count == 0

    # excess=51,000 -> fractional_lots=0.51 なら閾値0.5で1ロット売却
    target_weights = {"AAA": (100_000.0 - 51_000.0) / total_capital_actual}
    out_round_up = run_purge(
        phase=MacroPhase.CRUISE,
        holdings=holdings,
        target_weights=target_weights,
        current_prices=current_prices,
        total_capital_actual=total_capital_actual,
        lot_size=100,
        purge_lot_threshold=0.5,
    )
    assert out_round_up.total_count == 1
    assert out_round_up.items[0].shares_to_sell == 100

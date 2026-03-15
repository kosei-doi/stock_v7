"""dpa_macro のユニットテスト。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from core.dpa.dpa_macro import compute_vi_z, _phase_from_cash, get_macro_state
from core.dpa.dpa_schema import MacroPhase


def test_phase_from_cash():
    assert _phase_from_cash(0.25) == MacroPhase.CRUISE
    assert _phase_from_cash(0.4) == MacroPhase.CAUTION
    assert _phase_from_cash(0.6) == MacroPhase.REVERSAL
    assert _phase_from_cash(0.75) == MacroPhase.PANIC


def test_compute_vi_z():
    # 直近が平均より高い -> 正の Z（履歴に分散が必要なのでばらつかせる）
    np.random.seed(42)
    s = pd.Series(np.random.rand(61) * 5 + 15.0)  # 平均付近
    s.iloc[-1] = 30.0  # 直近だけ高い
    z = compute_vi_z(s, window=60)
    assert z is not None
    assert z > 0
    # 空
    assert compute_vi_z(pd.Series(dtype=float)) is None
    assert compute_vi_z(None) is None


def test_get_macro_state_returns_state():
    # 最小限の bench_df（MACD 用に少し長さが必要）
    dates = pd.date_range("2024-01-01", periods=50, freq="B")
    close = pd.Series(100.0 + np.cumsum(np.random.randn(50) * 0.5), index=dates)
    bench_df = pd.DataFrame({"close": close})
    state = get_macro_state(bench_df, vi_series=None, mu_cash=0.4, a_vi=0.1, b_macd=0.1)
    assert state.target_cash_ratio >= 0.2
    assert state.target_cash_ratio <= 0.8
    assert state.phase in (
        MacroPhase.CRUISE,
        MacroPhase.CAUTION,
        MacroPhase.REVERSAL,
        MacroPhase.PANIC,
    )
    assert state.phase_name_ja != ""

"""dpa_macro のユニットテスト。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from core.dpa.dpa_macro import compute_macd_trend, compute_vi_z, _phase_from_cash, get_macro_state
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


def test_compute_macd_trend_zscore_normalized():
    """MACD スプレッドの Z（クリップ後 /3）が [-1, 1] に入る。"""
    dates = pd.date_range("2024-01-01", periods=80, freq="B")
    rng = np.random.default_rng(0)
    close = pd.Series(100.0 + np.cumsum(rng.normal(0, 0.4, size=len(dates))), index=dates)
    bench_df = pd.DataFrame({"close": close})
    t = compute_macd_trend(bench_df, ma_window=5, z_window=60)
    assert t is not None
    assert -1.0 <= t <= 1.0


def test_compute_macd_trend_returns_none_if_too_short():
    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    bench_df = pd.DataFrame({"close": np.linspace(100, 101, len(dates))}, index=dates)
    assert compute_macd_trend(bench_df, ma_window=5, z_window=60) is None


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

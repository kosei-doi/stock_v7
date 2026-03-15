"""
DPA マクロ環境モジュール:
- TOPIX の MACD からトレンド指標（-1〜+1）を計算
- VI の履歴からZスコアを計算
- それらの連続値から 1 本の式で目標現金比率を決定し、
  フェーズ名（巡航/警戒/…）は後付けラベルとして付与する。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from core.dpa.dpa_schema import MacroPhase, MacroState
from core.dvc.indicators import compute_macd

# 1銘柄あたりの最大投資割合と絶対上限（資金防衛ルール用）
MAX_POSITION_PCT = 0.15
MAX_POSITION_JPY = 750_000

def compute_vi_z(vi_series: Optional[pd.Series], window: int = 60) -> Optional[float]:
    """VI のZスコア（直近値が過去 window 日の分布のどこにいるか）を返す。"""
    if vi_series is None or vi_series.empty:
        return None
    s = vi_series.dropna()
    if s.empty:
        return None
    if len(s) < window + 1:
        window = len(s) - 1
    if window <= 1:
        return None
    recent = float(s.iloc[-1])
    hist = s.iloc[-window - 1 : -1]
    arr = hist.to_numpy(dtype=float)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=0))
    if sigma == 0.0 or np.isnan(sigma):
        return None
    return float((recent - mu) / sigma)


def compute_macd_trend(
    bench_df: pd.DataFrame,
    window: int = 5,
    scale: float = 0.002,
) -> Optional[float]:
    """MACD とシグナルの差分 spread のトレンドを -1〜+1 に正規化した指標として返す。"""
    if bench_df is None or bench_df.empty or len(bench_df) < window + 2:
        return None
    macd, signal = compute_macd(bench_df)
    spread = macd - signal
    if isinstance(spread, pd.DataFrame):
        spread = spread.iloc[:, 0]
    spread = spread.dropna()
    if len(spread) < window + 1:
        return None
    recent = spread.iloc[-window:]
    old = spread.iloc[-window - 1 : -1]
    diff = float(recent.mean() - old.mean())
    if scale == 0.0:
        return None
    raw = diff / scale
    return float(max(-1.0, min(1.0, raw)))


def _continuous_cash_ratio(
    vi_z: Optional[float],
    macd_trend: Optional[float],
    mu_cash: float = 0.4,
    a_vi: float = 0.1,
    b_macd: float = 0.1,
    min_ratio: float = 0.2,
    max_ratio: float = 0.8,
) -> float:
    """VI ZスコアとMACDトレンドから連続的に現金比率を計算する。"""
    z = vi_z if vi_z is not None else 0.0
    t = macd_trend if macd_trend is not None else 0.0
    # 恐怖が高いほど現金比率↑、トレンド上向きほど現金比率↓
    cash = mu_cash + a_vi * max(z, 0.0) - b_macd * t
    if cash < min_ratio:
        cash = min_ratio
    if cash > max_ratio:
        cash = max_ratio
    return float(cash)


def _phase_from_cash(cash_ratio: float) -> MacroPhase:
    """現金比率からフェーズラベルを後付けで決める。"""
    if cash_ratio <= 0.3:
        return MacroPhase.CRUISE
    if cash_ratio <= 0.5:
        return MacroPhase.CAUTION
    if cash_ratio >= 0.7:
        return MacroPhase.PANIC
    return MacroPhase.REVERSAL


def get_macro_state(
    bench_df: pd.DataFrame,
    vi_series: Optional[pd.Series] = None,
    mu_cash: float = 0.4,
    a_vi: float = 0.1,
    b_macd: float = 0.1,
    macd_scale: float = 0.002,
    min_cash_ratio: float = 0.2,
    max_cash_ratio: float = 0.8,
) -> MacroState:
    """
    TOPIX の MACD トレンドと VI シリーズから連続的に現金比率を計算し、
    フェーズ名は現金比率から後付けで決める。
    """
    vi_z = compute_vi_z(vi_series)
    macd_trend = compute_macd_trend(bench_df, scale=macd_scale)
    cash_ratio = _continuous_cash_ratio(
        vi_z=vi_z,
        macd_trend=macd_trend,
        mu_cash=mu_cash,
        a_vi=a_vi,
        b_macd=b_macd,
        min_ratio=min_cash_ratio,
        max_ratio=max_cash_ratio,
    )
    phase = _phase_from_cash(cash_ratio)
    phase_name_ja = {
        MacroPhase.CRUISE: "巡航モード【オフェンス】",
        MacroPhase.CAUTION: "警戒モード【ロー・ベータ・シフト】",
        MacroPhase.PANIC: "パニック防衛モード【キャッシュ・イズ・キング】",
        MacroPhase.REVERSAL: "反転狙撃モード【バリュー・スナイプ】",
    }[phase]
    return MacroState(
        phase=phase,
        phase_name_ja=phase_name_ja,
        target_cash_ratio=cash_ratio,
        vi_z=vi_z,
        macd_trend=macd_trend,
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class ValueSignals:
    time_z_pb: Optional[float]
    time_z_pe: Optional[float]
    space_z_pb: Optional[float]
    space_z_pe: Optional[float]


@dataclass
class SafetySignals:
    f_score: Optional[float]
    altman_z: Optional[float]


@dataclass
class MomentumSignals:
    macd_cross_recent_days: Optional[int]
    macd_slope_at_cross: Optional[float]
    volume_z: Optional[float]


@dataclass
class MarketRiskSignals:
    beta: Optional[float]
    r_squared: Optional[float]
    alpha: Optional[float]
    atr_percent: Optional[float]


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_macd(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """close 列を前提とする。data_fetcher.normalize_price_columns を通した DataFrame を渡すこと。"""
    if df is None or df.empty or "close" not in df.columns:
        raise ValueError("DataFrame に 'close' 列がありません。normalize_price_columns 済みの株価 DataFrame を渡してください。")
    close = df["close"]
    # yfinanceの仕様により単一ティッカーでも列がDataFrameになる場合に対応
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd = ema12 - ema26
    signal = _ema(macd, 9)
    return macd, signal


def detect_macd_cross(df: pd.DataFrame) -> Tuple[Optional[int], Optional[float]]:
    macd, signal = compute_macd(df)
    spread = macd - signal
    if isinstance(spread, pd.DataFrame):
        spread = spread.iloc[:, 0]
    if spread.isna().all():
        return None, None

    cross_indices = np.where((spread.shift(1) < 0) & (spread > 0))[0]
    if len(cross_indices) == 0:
        return None, None

    last_cross_idx = cross_indices[-1]
    days_since_cross = len(spread) - 1 - last_cross_idx
    if last_cross_idx >= 1:
        slope = spread.iloc[last_cross_idx] - spread.iloc[last_cross_idx - 1]
    else:
        slope = None
    return int(days_since_cross), float(slope) if slope is not None else None


def compute_volume_zscore(df: pd.DataFrame, window: int = 20) -> Optional[float]:
    if df is None or df.empty or "volume" not in df.columns:
        return None
    vol = df["volume"]
    if isinstance(vol, pd.DataFrame):
        vol = vol.iloc[:, 0]
    vol = vol.dropna()
    if len(vol) < window + 1:
        return None
    recent = vol.iloc[-1]
    hist = vol.iloc[-window - 1 : -1]
    arr = hist.to_numpy(dtype=float)
    mean = float(arr.mean())
    std = float(arr.std(ddof=0))
    if std == 0.0 or np.isnan(std):
        return None
    return float((recent - mean) / std)


def compute_atr_percent(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """high / low / close 列を前提。data_fetcher.normalize_price_columns 済みの DataFrame を渡すこと。"""
    if df is None or df.empty:
        return None
    for col in ("high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"DataFrame に '{col}' 列がありません。normalize_price_columns 済みの株価 DataFrame を渡してください。")
    high = df["high"]
    low = df["low"]
    close = df["close"]
    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]
    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    last_atr = atr.iloc[-1]
    last_close = close.iloc[-1]
    if pd.isna(last_atr) or last_close == 0:
        return None
    return float(last_atr / last_close * 100.0)


def compute_returns(df: pd.DataFrame) -> pd.Series:
    """close 列を前提。data_fetcher.normalize_price_columns 済みの DataFrame を渡すこと。"""
    if df is None or df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)
    close = df["close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.pct_change().dropna()


def compute_beta_and_r2(
    stock_df: pd.DataFrame, benchmark_df: pd.DataFrame
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    stock_ret = compute_returns(stock_df)
    bench_ret = compute_returns(benchmark_df)
    joined = pd.concat([stock_ret, bench_ret], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return None, None, None

    y = joined.iloc[:, 0].values
    x = joined.iloc[:, 1].values
    slope, intercept, r_value, _, _ = stats.linregress(x, y)
    beta = float(slope)
    alpha = float(intercept)
    r_squared = float(r_value**2)
    return beta, r_squared, alpha


def compute_value_time_zscores(
    price_df: pd.DataFrame,
    book_value_per_share: Optional[float],
    eps_ttm: Optional[float],
) -> Tuple[Optional[float], Optional[float]]:
    close = price_df["close"]
    pb_series = None
    pe_series = None

    if book_value_per_share and book_value_per_share != 0:
        pb_series = close / book_value_per_share
    if eps_ttm and eps_ttm != 0:
        pe_series = close / eps_ttm

    def _z(series: Optional[pd.Series]) -> Optional[float]:
        if series is None or series.empty:
            return None
        arr = series.to_numpy(dtype=float)
        if arr.size < 2:
            return None
        mu = float(arr.mean())
        sigma = float(arr.std(ddof=0))
        if sigma == 0.0 or np.isnan(sigma):
            return None
        current = float(arr[-1])
        return float((current - mu) / sigma)

    return _z(pb_series), _z(pe_series)


def compute_value_space_zscores(
    target_pb: Optional[float],
    target_pe: Optional[float],
    peer_pbs: list[float],
    peer_pes: list[float],
) -> Tuple[Optional[float], Optional[float]]:
    def _z(target: Optional[float], peers: list[float]) -> Optional[float]:
        vals = [v for v in peers if v is not None]
        if target is None or not vals:
            return None
        arr = np.array(vals, dtype=float)
        mu = arr.mean()
        sigma = arr.std(ddof=0)
        if sigma == 0 or np.isnan(sigma):
            return None
        return float((target - mu) / sigma)

    return _z(target_pb, peer_pbs), _z(target_pe, peer_pes)


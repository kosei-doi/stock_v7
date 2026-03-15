from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import yfinance as yf


# yfinance が返す列名（大文字）を小文字に統一するマッピング
_PRICE_COLUMN_RENAME = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
}


def normalize_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    yfinance 由来の DataFrame の列名を小文字に正規化する。
    MultiIndex 列の場合は先頭レベルだけをリネームする。
    """
    if df is None or df.empty:
        return df
    cols = df.columns
    if hasattr(cols, "get_level_values"):
        # MultiIndex: 先頭要素でマッピング
        new_cols = []
        for c in cols:
            key = c[0] if isinstance(c, (tuple, list)) and len(c) > 0 else c
            new_cols.append(_PRICE_COLUMN_RENAME.get(key, key))
        df = df.copy()
        df.columns = new_cols
    else:
        df = df.rename(columns=_PRICE_COLUMN_RENAME)
    return df


def get_close_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """正規化済みの DataFrame から 'close' 列を 1 本の Series として返す。無い場合は None。"""
    if df is None or df.empty:
        return None
    if "close" not in df.columns:
        return None
    close = df["close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna() if hasattr(close, "dropna") else close


@dataclass
class FundamentalSnapshot:
    shares_outstanding: Optional[float]
    book_value_per_share: Optional[float]
    eps_ttm: Optional[float]
    sector: Optional[str]
    long_name: Optional[str]


def fetch_price_history(ticker: str, years: int) -> pd.DataFrame:
    """日足株価データを取得する。列名は normalize_price_columns で小文字に統一される。"""
    df = yf.download(ticker, period=f"{years}y", interval="1d", auto_adjust=False)
    return normalize_price_columns(df) if df is not None and not df.empty else (df if df is not None else pd.DataFrame())


def fetch_fundamentals(ticker: str) -> FundamentalSnapshot:
    """yfinance.Ticker.info から必要なファンダメンタル情報を抜き出す。"""
    tk = yf.Ticker(ticker)
    info = tk.info or {}

    shares_outstanding = info.get("sharesOutstanding")
    book_value = info.get("bookValue")
    eps_ttm = info.get("trailingEps")

    sector = info.get("sector")
    long_name = info.get("longName") or info.get("shortName")

    book_value_per_share = None
    if shares_outstanding and book_value:
        try:
            book_value_per_share = float(book_value)
        except (TypeError, ValueError):
            book_value_per_share = None

    return FundamentalSnapshot(
        shares_outstanding=shares_outstanding,
        book_value_per_share=book_value_per_share,
        eps_ttm=eps_ttm,
        sector=sector,
        long_name=long_name,
    )


def fetch_benchmark_history(benchmark_ticker: str, years: int) -> pd.DataFrame:
    """ベンチマーク指数（日足）を取得する。"""
    return fetch_price_history(benchmark_ticker, years)


def fetch_vi_latest(vi_ticker: str) -> Optional[float]:
    """
    ボラティリティ指数（VI）の直近終値を取得する。
    日本株なら日経VIなど国内指標を指定すること（^VIX は米国指標のため日本株向けには不向き）。
    取得失敗時は None。
    """
    if not vi_ticker or not vi_ticker.strip():
        return None
    df = yf.download(vi_ticker, period="5d", interval="1d", auto_adjust=False, progress=False)
    if df is None or df.empty:
        return None
    df = normalize_price_columns(df)
    close = get_close_series(df)
    if close is None or close.empty:
        return None
    last = close.iloc[-1]
    if isinstance(last, pd.Series):
        last = last.iloc[0]
    try:
        return float(last)
    except (TypeError, ValueError):
        return None


def fetch_sector_peers_map(path: str) -> dict:
    """sector_peers.json を読み込む。ファイル不在・不正時は {} を返す。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def get_sector_peers(
    sector_name: Optional[str], peers_map: dict
) -> Tuple[Optional[str], list[str]]:
    """セクター名をキーに代表銘柄リストを取得する。見つからない場合は空リストを返す。"""
    if sector_name is None:
        return None, []

    if sector_name in peers_map:
        return sector_name, list(peers_map[sector_name])

    # 部分一致や拡張表現（例: 小売業_外食 vs 小売業）の簡易フォールバック
    for key in peers_map.keys():
        if sector_name in key or key in sector_name:
            return key, list(peers_map[key])

    return None, []


"""data_fetcher の列正規化などのユニットテスト。"""
from __future__ import annotations

import pandas as pd
import pytest

from core.dvc.data_fetcher import get_close_series, normalize_price_columns


def test_normalize_price_columns_lowercase():
    """大文字列名が小文字に変換される。"""
    df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
    out = normalize_price_columns(df)
    assert "close" in out.columns
    assert "open" in out.columns
    assert out["close"].iloc[0] == 1.5


def test_normalize_price_columns_empty():
    """空 DataFrame はそのまま返る。"""
    df = pd.DataFrame()
    out = normalize_price_columns(df)
    assert out.empty


def test_get_close_series():
    """close 列から 1 本の Series を返す。"""
    df = pd.DataFrame({"close": [100.0, 101.0, 99.0]})
    s = get_close_series(df)
    assert s is not None
    assert len(s) == 3
    assert s.iloc[-1] == 99.0


def test_get_close_series_no_close():
    """close が無い場合は None。"""
    df = pd.DataFrame({"Open": [1], "Close": [2]})  # 未正規化
    assert get_close_series(df) is None
    df2 = pd.DataFrame({"other": [1, 2, 3]})
    assert get_close_series(df2) is None


def test_get_close_series_empty():
    assert get_close_series(pd.DataFrame()) is None
    assert get_close_series(None) is None

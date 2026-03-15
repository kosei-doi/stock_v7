"""daily_cache の cache_is_fresh 判定のユニットテスト。"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from core.utils.daily_cache import cache_is_fresh

# テスト用: Asia/Tokyo が使えない環境でも datetime で日付を渡すので zoneinfo 不要


def test_cache_is_fresh_none():
    assert cache_is_fresh(None, benchmark_ticker="1306.T", years=5) is False


def test_cache_is_fresh_ticker_mismatch():
    cache = {"benchmark_ticker": "1306.T", "years": 5, "updated_date": "2024-01-15"}
    assert cache_is_fresh(cache, benchmark_ticker="9999.T", years=5) is False
    assert cache_is_fresh(cache, benchmark_ticker="1306.T", years=3) is False


def test_cache_is_fresh_no_updated_date():
    cache = {"benchmark_ticker": "1306.T", "years": 5}
    assert cache_is_fresh(cache, benchmark_ticker="1306.T", years=5) is False


def test_cache_is_fresh_with_now_weekday_after_cutoff():
    """平日・カットオフ後: updated_date が今日なら fresh。"""
    today = date(2024, 6, 3)  # 月曜
    now = datetime(2024, 6, 3, 10, 0, 0)  # 10:00
    cache = {"benchmark_ticker": "1306.T", "years": 5, "updated_date": "2024-06-03"}
    assert cache_is_fresh(cache, benchmark_ticker="1306.T", years=5, now=now) is True
    cache["updated_date"] = "2024-06-02"
    assert cache_is_fresh(cache, benchmark_ticker="1306.T", years=5, now=now) is False


def test_cache_is_fresh_weekend():
    """週末: 金曜付きのキャッシュなら fresh。"""
    sat = datetime(2024, 6, 8, 12, 0, 0)  # 土曜
    cache = {"benchmark_ticker": "1306.T", "years": 5, "updated_date": "2024-06-07"}  # 金曜
    assert cache_is_fresh(cache, benchmark_ticker="1306.T", years=5, now=sat) is True

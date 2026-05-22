"""watchlist_io のユニットテスト（追加購入・加重平均）。"""
from __future__ import annotations

import json

import pytest

from core.utils.watchlist_io import (
    load_watchlist,
    save_watchlist,
    update_holdings_bulk,
    STATUS_HOLDING,
)


def test_update_holdings_bulk_adds_shares_and_weighted_avg(tmp_path):
    """同一 ticker を 2 回更新すると株数が加算され、平均単価は加重平均になる。"""
    path = tmp_path / "watchlist.json"
    save_watchlist(
        [{"ticker": "7203.T", "status": STATUS_HOLDING, "shares": 100, "avg_price": 1000.0}],
        path=str(path),
    )

    update_holdings_bulk(
        {"7203.T": {"shares": 100, "avg_price": 2000.0}},
        path=str(path),
    )

    items = load_watchlist(str(path))
    holding = next(i for i in items if i["ticker"] == "7203.T")
    assert holding["shares"] == 200
    assert holding["avg_price"] == pytest.approx(1500.0)


def test_update_holdings_bulk_new_holding_sets_values(tmp_path):
    """新規 HOLDING は渡された shares / avg_price をそのまま設定する。"""
    path = tmp_path / "watchlist.json"
    save_watchlist([], path=str(path))

    update_holdings_bulk(
        {"9984.T": {"shares": 300, "avg_price": 8500.0}},
        path=str(path),
    )

    items = load_watchlist(str(path))
    assert len(items) == 1
    assert items[0]["ticker"] == "9984.T"
    assert items[0]["status"] == STATUS_HOLDING
    assert items[0]["shares"] == 300
    assert items[0]["avg_price"] == pytest.approx(8500.0)


def test_update_holdings_bulk_add_without_avg_keeps_existing_avg(tmp_path):
    """追加分に avg_price が無い場合は既存の平均単価を維持する。"""
    path = tmp_path / "watchlist.json"
    save_watchlist(
        [{"ticker": "7203.T", "status": STATUS_HOLDING, "shares": 100, "avg_price": 1200.0}],
        path=str(path),
    )

    update_holdings_bulk({"7203.T": {"shares": 50}}, path=str(path))

    holding = load_watchlist(str(path))[0]
    assert holding["shares"] == 150
    assert holding["avg_price"] == pytest.approx(1200.0)

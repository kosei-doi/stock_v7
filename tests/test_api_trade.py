"""trade API の TestClient テスト（認証・バリデーション・ticker 正規化）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DPA_CLIENT_HEADERS


@pytest.fixture
def trade_env(file_persistence, monkeypatch):
    """取引 API 用の File 永続化と TestClient。"""
    bundle, paths = file_persistence
    paths.watchlist_path.write_text("[]", encoding="utf-8")
    paths.portfolio_path.write_text(json.dumps({"cash_yen": 1_000_000}), encoding="utf-8")
    paths.last_report_path.write_text(
        json.dumps({"last_prices": {"7203.T": 2500.0}}),
        encoding="utf-8",
    )

    import web.api as api

    monkeypatch.setattr(api, "_run_dvc_for_ticker", lambda _ticker: None)

    from web.main import create_app

    client = TestClient(create_app())
    yield client, paths


def test_trade_purchase_requires_api_key_when_set(trade_env, monkeypatch):
    client, *_ = trade_env
    monkeypatch.setenv("DPA_API_KEY", "test-secret-key")
    body = {"ticker": "7203", "shares": 100, "avg_price": 2500.0}

    resp = client.post("/api/trade/purchase", json=body, headers=DPA_CLIENT_HEADERS)
    assert resp.status_code == 401

    resp = client.post(
        "/api/trade/purchase",
        json=body,
        headers={**DPA_CLIENT_HEADERS, "X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_trade_purchase_rejects_insufficient_cash(trade_env):
    client, paths = trade_env
    paths.portfolio_path.write_text(json.dumps({"cash_yen": 1000}), encoding="utf-8")

    resp = client.post(
        "/api/trade/purchase",
        json={"ticker": "7203", "shares": 100, "avg_price": 2500.0},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 400
    assert "現金不足" in resp.json()["detail"]


def test_trade_purchase_normalizes_ticker(trade_env):
    client, paths = trade_env
    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "WATCHING"}]),
        encoding="utf-8",
    )
    paths.portfolio_path.write_text(json.dumps({"cash_yen": 1_000_000}), encoding="utf-8")

    resp = client.post(
        "/api/trade/purchase",
        json={"ticker": "7203", "shares": 100, "avg_price": 2500.0},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    items = json.loads(paths.watchlist_path.read_text(encoding="utf-8"))
    holding = next(i for i in items if i.get("ticker") == "7203.T")
    assert holding["status"] == "HOLDING"
    assert holding["shares"] == 100
    assert holding["avg_price"] == pytest.approx(2500.0)


def test_trade_sale_rejects_missing_price(trade_env):
    client, paths = trade_env
    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "HOLDING", "shares": 200}]),
        encoding="utf-8",
    )
    paths.last_report_path.write_text(json.dumps({"last_prices": {}}), encoding="utf-8")

    resp = client.post(
        "/api/trade/sale",
        json={"ticker": "7203", "shares": 100},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 400
    assert "株価データがありません" in resp.json()["detail"]


def test_trade_sale_rejects_not_holding(trade_env):
    client, paths = trade_env
    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "WATCHING"}]),
        encoding="utf-8",
    )

    resp = client.post(
        "/api/trade/sale",
        json={"ticker": "7203", "shares": 100},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 400
    assert "保有銘柄ではありません" in resp.json()["detail"]


def test_trade_sale_rejects_excess_shares(trade_env):
    client, paths = trade_env
    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "HOLDING", "shares": 100}]),
        encoding="utf-8",
    )

    resp = client.post(
        "/api/trade/sale",
        json={"ticker": "7203.T", "shares": 200},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 400
    assert "保有株数" in resp.json()["detail"]


def test_trade_purchase_floors_fractional_cost(trade_env):
    """購入額・現金残高は整数円（切り捨て）。"""
    client, paths = trade_env
    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "WATCHING"}]),
        encoding="utf-8",
    )
    paths.portfolio_path.write_text(json.dumps({"cash_yen": 1_000_000}), encoding="utf-8")

    resp = client.post(
        "/api/trade/purchase",
        json={"ticker": "7203", "shares": 100, "avg_price": 2500.99},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["cash_yen"] == 750_000

    items = json.loads(paths.watchlist_path.read_text(encoding="utf-8"))
    holding = next(i for i in items if i.get("ticker") == "7203.T")
    assert holding["avg_price"] == 2500
    assert holding["shares"] == 100


def test_trade_sale_normalizes_ticker(trade_env):
    client, paths = trade_env
    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "HOLDING", "shares": 200}]),
        encoding="utf-8",
    )
    paths.portfolio_path.write_text(json.dumps({"cash_yen": 0}), encoding="utf-8")

    resp = client.post(
        "/api/trade/sale",
        json={"ticker": "7203", "shares": 100},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["cash_yen"] == pytest.approx(250_000.0)

    items = json.loads(paths.watchlist_path.read_text(encoding="utf-8"))
    holding = next(i for i in items if i.get("ticker") == "7203.T")
    assert holding["shares"] == 100


def test_trade_purchase_with_sqlite(sqlite_persistence, monkeypatch):
    """SQLite :memory: で購入・現金控除・HOLDING 更新。"""
    bundle, _paths = sqlite_persistence
    bundle.watchlist.save_all([{"ticker": "7203.T", "status": "WATCHING"}])
    bundle.portfolio.set_cash_yen(1_000_000)
    bundle.daily_report.save_last({"last_prices": {"7203.T": 2500.0}})

    import web.api as api

    monkeypatch.setattr(api, "_run_dvc_for_ticker", lambda _ticker: None)

    from web.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/api/trade/purchase",
        json={"ticker": "7203", "shares": 100, "avg_price": 2500.0},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["cash_yen"] == 750_000
    assert bundle.portfolio.get_cash_yen() == 750_000
    holding = next(
        i for i in bundle.watchlist.load_all() if (i.get("ticker") or "") == "7203.T"
    )
    assert holding["status"] == "HOLDING"
    assert holding["shares"] == 100

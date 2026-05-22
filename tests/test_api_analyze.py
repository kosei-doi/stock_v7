"""企業分析 API（一覧・詳細・OHLC）のスモークテスト。"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient


def _seed_analyze_bundle(bundle, paths) -> None:
    bundle.watchlist.save_all(
        [
            {"ticker": "7203.T", "status": "WATCHING"},
            {"ticker": "9984.T", "status": "HOLDING", "shares": 100},
        ]
    )
    paths.watchlist_path.write_text(
        json.dumps(
            [
                {"ticker": "7203.T", "status": "WATCHING"},
                {"ticker": "9984.T", "status": "HOLDING", "shares": 100},
            ]
        ),
        encoding="utf-8",
    )
    bundle.ticker_analysis.save(
        "7203.T",
        {
            "ticker": "7203.T",
            "name": "Toyota",
            "scores": {
                "total_score": 62.5,
                "value_score": 40,
                "safety_score": 90,
                "momentum_score": 35,
            },
            "data_overview": {"price_history": {"last_close": 3000}},
        },
    )
    bundle.daily_report.save_last(
        json.loads(
            json.dumps({"ticker_names": {"9984.T": "SoftBank"}, "last_prices": {"9984.T": 8000}})
        )
    )


@pytest.fixture
def analyze_client(file_persistence, monkeypatch):
    bundle, paths = file_persistence
    _seed_analyze_bundle(bundle, paths)
    config = paths.project_root / "config.yaml"
    config.write_text("years: 3\noutput_dir: output\n", encoding="utf-8")

    import web.api as api

    monkeypatch.setattr(api, "CONFIG_PATH", config)
    monkeypatch.setattr(api, "PROJECT_ROOT", paths.project_root)
    monkeypatch.chdir(paths.project_root)

    from web.main import create_app

    return TestClient(create_app())


@pytest.fixture
def analyze_client_sqlite(sqlite_persistence, monkeypatch):
    bundle, paths = sqlite_persistence
    _seed_analyze_bundle(bundle, paths)
    config = paths.project_root / "config.yaml"
    config.write_text("years: 3\noutput_dir: output\n", encoding="utf-8")

    import web.api as api

    monkeypatch.setattr(api, "CONFIG_PATH", config)
    monkeypatch.setattr(api, "PROJECT_ROOT", paths.project_root)
    monkeypatch.chdir(paths.project_root)

    from web.main import create_app

    return TestClient(create_app())


def test_watchlist_analysis_index(analyze_client):
    resp = analyze_client.get("/api/watchlist/analysis-index")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    by_ticker = {i["ticker"]: i for i in items}
    assert by_ticker["7203.T"]["has_output"] is True
    assert by_ticker["7203.T"]["total_score"] == pytest.approx(62.5)
    assert by_ticker["9984.T"]["has_output"] is False
    assert by_ticker["9984.T"]["name"] == "SoftBank"


def test_watchlist_analysis_index_sqlite(analyze_client_sqlite):
    resp = analyze_client_sqlite.get("/api/watchlist/analysis-index")
    assert resp.status_code == 200
    by_ticker = {i["ticker"]: i for i in resp.json()["items"]}
    assert by_ticker["7203.T"]["has_output"] is True
    assert by_ticker["7203.T"]["total_score"] == pytest.approx(62.5)


def test_ticker_analysis_404(analyze_client):
    resp = analyze_client.get("/api/ticker/9984.T/analysis")
    assert resp.status_code == 404


def test_ticker_analysis_ok(analyze_client):
    resp = analyze_client.get("/api/ticker/7203.T/analysis")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "7203.T"
    assert data["name"] == "Toyota"
    assert data["total_score"] == pytest.approx(62.5)


def test_ticker_analysis_ok_sqlite(analyze_client_sqlite):
    resp = analyze_client_sqlite.get("/api/ticker/7203.T/analysis")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Toyota"


def test_ticker_ohlc(analyze_client, monkeypatch):
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [99.0, 100.0, 101.0],
            "close": [104.0, 105.0, 106.0],
        },
        index=dates,
    )

    def fake_fetch(_ticker: str, _years: int):
        return df

    monkeypatch.setattr("core.dvc.data_fetcher.fetch_price_history", fake_fetch)

    resp = analyze_client.get("/api/ticker/7203/ohlc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["years"] == 1
    bars = body["bars"]
    assert len(bars) == 3
    assert bars[0]["time"] == "2024-01-01"
    assert bars[-1]["close"] == pytest.approx(106.0)

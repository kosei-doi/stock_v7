"""GET /api/report/merged の SQLite スモーク（DB-7）。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import DPA_CLIENT_HEADERS


def _seed_report(bundle) -> None:
    bundle.watchlist.save_all(
        [
            {"ticker": "7203.T", "status": "HOLDING", "shares": 100, "avg_price": 2000.0},
        ]
    )
    bundle.daily_report.save_last(
        {
            "data_date": "2026-05-22",
            "ticker_names": {"7203.T": "Toyota"},
            "last_prices": {"7203.T": 2500.0},
            "portfolio_scores": {"7203.T": 70.0},
            "current_weights": {"7203.T": 0.5},
            "target_weights": {"7203.T": 0.4},
            "score_trends": {
                "7203.T": {"last": 70.0, "level": 70.0, "trend": 0.0},
            },
        }
    )
    bundle.daily_report.save_previous(
        {
            "data_date": "2026-05-21",
            "last_prices": {"7203.T": 2400.0},
            "portfolio_scores": {"7203.T": 65.0},
        }
    )


def test_report_merged_sqlite(sqlite_persistence, monkeypatch):
    bundle, paths = sqlite_persistence
    _seed_report(bundle)

    paths.watchlist_path.write_text(
        json.dumps([{"ticker": "7203.T", "status": "HOLDING", "shares": 100, "avg_price": 2000.0}]),
        encoding="utf-8",
    )

    from web.main import create_app

    client = TestClient(create_app())
    resp = client.get("/api/report/merged")
    assert resp.status_code == 200
    body = resp.json()
    assert body["report"] is not None
    assert body["report"]["data_date"] == "2026-05-22"
    holdings = body["holdings_merged"]
    assert len(holdings) >= 1
    h = next(x for x in holdings if x["ticker"] == "7203.T")
    assert h["name"] == "Toyota"
    assert h["shares"] == 100


def test_report_merged_empty_sqlite(sqlite_persistence):
    from web.main import create_app

    client = TestClient(create_app())
    resp = client.get("/api/report/merged")
    assert resp.status_code == 200
    assert resp.json()["report"] is None

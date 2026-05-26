"""GET /report ページのスモーク（モーダル共通化）。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DPA_CLIENT_HEADERS, file_persistence


@pytest.fixture
def report_client(file_persistence):
    bundle, paths = file_persistence
    data_dir = paths.data_dir
    (data_dir / "last_report.json").write_text(
        json.dumps(
            {
                "data_date": "2026-05-22",
                "created_at": "2026-05-22 08:00:00 JST",
                "ticker_names": {"7203.T": "トヨタ"},
                "last_prices": {"7203.T": 2500},
                "portfolio_scores": {"7203.T": 70.0},
                "holdings": [{"ticker": "7203.T", "name": "トヨタ"}],
                "target_weights": {"7203.T": 0.1},
                "current_weights": {"7203.T": 0.12},
                "score_trends": {"7203.T": {"trend": 0.5}},
            }
        ),
        encoding="utf-8",
    )
    bundle.watchlist.save_all([{"ticker": "7203.T", "status": "HOLDING", "shares": 100}])
    bundle.ticker_analysis.save(
        "7203.T",
        {
            "ticker": "7203.T",
            "name": "トヨタ",
            "scores": {"total_score": 70.0, "value_score": 60.0, "safety_score": 80.0, "momentum_score": 50.0},
        },
    )

    from web.main import create_app

    return TestClient(create_app())


def test_report_page_includes_modal_assets(report_client):
    """日次レポートは銘柄行に data-ticker を持ち、モーダルアセットを base.html 経由で読み込む。"""
    resp = report_client.get("/report", headers=DPA_CLIENT_HEADERS)
    assert resp.status_code == 200
    html = resp.text
    assert "id=\"detail-modal\"" in html
    assert "report-ticker-row" in html
    assert "/static/js/ticker_detail_modal.js" in html


def test_report_page_without_report(file_persistence):
    """レポート未生成時もモーダル本体は base.html 経由で全ページに含まれる。"""
    from web.main import create_app

    client = TestClient(create_app())
    resp = client.get("/report", headers=DPA_CLIENT_HEADERS)
    assert resp.status_code == 200
    assert "レポートがありません" in resp.text
    # base.html がモーダルを共通注入するので任意ページで利用可能
    assert "ticker_detail_modal.js" in resp.text

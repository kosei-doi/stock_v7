"""設定保存: YAML の null ネストでも落ちないことのテスト。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DPA_CLIENT_HEADERS


@pytest.fixture
def settings_client(file_persistence, monkeypatch):
    bundle, paths = file_persistence
    paths.portfolio_path.write_text(json.dumps({"cash_yen": 1_000_000}), encoding="utf-8")
    config = paths.project_root / "config.yaml"
    config.write_text("benchmark_ticker: 1306.T\nyears: 5\ndpa: {}\n", encoding="utf-8")

    import web.api as api

    monkeypatch.setattr(api, "CONFIG_PATH", config)
    monkeypatch.setattr(api, "PROJECT_ROOT", paths.project_root)
    monkeypatch.chdir(paths.project_root)

    from web.main import create_app

    return TestClient(create_app())


def test_settings_update_rejects_unknown_field(settings_client):
    resp = settings_client.post(
        "/api/settings/update",
        json={"cash_yen": 100, "unknown_key": 1},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 422


def test_settings_update_rejects_out_of_range_watchlist_max(settings_client):
    resp = settings_client.post(
        "/api/settings/update",
        json={"watchlist_max_items": 3},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 422


def test_settings_update_accepts_valid_patch(settings_client, monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {"benchmark_ticker": "1306.T", "years": 5, "dpa": {}, "watchlist": {"max_items": 30}},
    )
    resp = settings_client.post(
        "/api/settings/update",
        json={"watchlist_max_items": 40, "purge_lot_threshold": 0.6},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_settings_update_cash_sqlite(sqlite_persistence, monkeypatch):
    """SQLite portfolio で cash_yen 更新。"""
    bundle, paths = sqlite_persistence
    bundle.portfolio.set_cash_yen(1_000_000)
    config = paths.project_root / "config.yaml"
    config.write_text("benchmark_ticker: 1306.T\nyears: 5\ndpa: {}\n", encoding="utf-8")

    import web.api as api

    monkeypatch.setattr(api, "CONFIG_PATH", config)
    monkeypatch.setattr(api, "PROJECT_ROOT", paths.project_root)
    monkeypatch.chdir(paths.project_root)

    from web.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/api/settings/update",
        json={"cash_yen": 2_500_000},
        headers=DPA_CLIENT_HEADERS,
    )
    assert resp.status_code == 200
    assert bundle.portfolio.get_cash_yen() == 2_500_000


def test_flat_to_config_repairs_null_watchlist(monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {
            "watchlist": None,
            "benchmark_ticker": "1306.T",
            "dpa": {"vi_ticker": "^VIX"},
        },
    )
    cfg = api._flat_to_config({"watchlist_max_items": 50})
    assert isinstance(cfg["watchlist"], dict)
    assert cfg["watchlist"]["max_items"] == 50


def test_flat_to_config_repairs_null_dpa(monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {"benchmark_ticker": "1306.T", "dpa": None},
    )
    cfg = api._flat_to_config({"vi_ticker": "^VIX"})
    assert isinstance(cfg["dpa"], dict)
    assert cfg["dpa"]["vi_ticker"] == "^VIX"


def test_flat_to_config_accepts_purge_lot_threshold(monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {"benchmark_ticker": "1306.T", "dpa": {}},
    )
    cfg = api._flat_to_config({"purge_lot_threshold": 0.65})
    assert cfg["dpa"]["purge_lot_threshold"] == 0.65

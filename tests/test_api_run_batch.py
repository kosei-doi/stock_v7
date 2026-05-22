"""run_batch API の CSRF ヘッダ・レート制限テスト。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DPA_CLIENT_HEADERS


@pytest.fixture
def batch_client(file_persistence, monkeypatch):
    bundle, paths = file_persistence
    paths.run_status_path.write_text(
        json.dumps({"status": "idle", "message": "", "step": None, "total_steps": 7}),
        encoding="utf-8",
    )

    import web.api as api

    monkeypatch.setattr(api, "_run_batch_background", lambda: None)

    from web.main import create_app

    return TestClient(create_app())


def test_run_batch_requires_dpa_client_header(batch_client):
    resp = batch_client.post("/api/run_batch")
    assert resp.status_code == 403
    assert "アプリ画面" in resp.json()["detail"]


def test_run_batch_rate_limit_returns_429(batch_client, monkeypatch):
    import web.api as api

    monkeypatch.setattr(api, "_write_run_status", lambda *args, **kwargs: None)

    headers = DPA_CLIENT_HEADERS
    for i in range(3):
        resp = batch_client.post("/api/run_batch", headers=headers)
        assert resp.status_code == 200, f"request {i + 1} failed: {resp.status_code} {resp.text}"

    resp = batch_client.post("/api/run_batch", headers=headers)
    assert resp.status_code == 429


def test_run_batch_status_sqlite(sqlite_persistence, monkeypatch):
    """SQLite run_job 経由で get_status が idle を返す。"""
    bundle, _paths = sqlite_persistence
    bundle.run_job.update_status("idle", "", step=None, total_steps=7)

    import web.api as api

    monkeypatch.setattr(api, "_run_batch_background", lambda: None)

    from web.main import create_app

    client = TestClient(create_app())
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"


def test_run_batch_conflict_when_running_sqlite(sqlite_persistence, monkeypatch):
    bundle, _paths = sqlite_persistence
    bundle.run_job.update_status("running", "busy", step=1)

    import web.api as api

    monkeypatch.setattr(api, "_run_batch_background", lambda: None)
    monkeypatch.setattr(api.limiter, "enabled", False)

    from web.main import create_app

    client = TestClient(create_app())
    resp = client.post("/api/run_batch", headers=DPA_CLIENT_HEADERS)
    assert resp.status_code == 409
    assert "実行中" in resp.json()["detail"]

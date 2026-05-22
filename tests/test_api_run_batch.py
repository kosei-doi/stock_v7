"""run_batch API の CSRF ヘッダ・レート制限テスト。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.persistence import (
    PersistencePaths,
    build_file_repositories,
    reset_persistence,
    set_persistence,
)

DPA_CLIENT_HEADERS = {"X-DPA-Client": "1"}


@pytest.fixture
def batch_client(tmp_path, monkeypatch):
    monkeypatch.delenv("DPA_API_KEY", raising=False)
    reset_persistence()

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    paths = PersistencePaths(
        project_root=tmp_path,
        data_dir=tmp_path,
        output_dir=output_dir,
    )
    set_persistence(build_file_repositories(paths))
    paths.run_status_path.write_text(
        json.dumps({"status": "idle", "message": "", "step": None, "total_steps": 7}),
        encoding="utf-8",
    )

    import web.api as api

    monkeypatch.setattr(api, "_run_batch_background", lambda: None)

    from web.main import create_app

    client = TestClient(create_app())
    yield client
    reset_persistence()


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

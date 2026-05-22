"""永続化レイヤ付き API テスト用の共通フィクスチャ（DB-7）。"""
from __future__ import annotations

import pytest

from core.persistence import (
    PersistencePaths,
    build_file_repositories,
    build_sqlite_repositories,
    reset_persistence,
    set_persistence,
)

DPA_CLIENT_HEADERS = {"X-DPA-Client": "1"}


@pytest.fixture
def persistence_paths(tmp_path):
    """一時プロジェクトルート + data/ + output/。"""
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return PersistencePaths(
        project_root=tmp_path,
        data_dir=data_dir,
        output_dir=output_dir,
    )


@pytest.fixture
def file_persistence(persistence_paths, monkeypatch):
    """File Repository + set_persistence（テスト後に reset）。"""
    monkeypatch.delenv("DPA_API_KEY", raising=False)
    monkeypatch.delenv("DPA_PERSISTENCE", raising=False)
    reset_persistence()
    bundle = build_file_repositories(persistence_paths)
    set_persistence(bundle)
    yield bundle, persistence_paths
    reset_persistence()


@pytest.fixture
def sqlite_persistence(persistence_paths, monkeypatch):
    """SQLite Repository + set_persistence（テストごとに独立した tmp db）。"""
    monkeypatch.delenv("DPA_API_KEY", raising=False)
    monkeypatch.setenv("DPA_PERSISTENCE", "sqlite")
    reset_persistence()
    db_path = (persistence_paths.data_dir / "test.db").resolve()
    database_url = f"sqlite:///{db_path}"
    bundle = build_sqlite_repositories(persistence_paths, database_url=database_url)
    set_persistence(bundle)
    yield bundle, persistence_paths
    reset_persistence()

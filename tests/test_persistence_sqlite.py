"""SQLite Repository のスモークテスト（DB-3 フェーズ B）。"""
from __future__ import annotations

import pytest

from core.persistence import (
    PersistencePaths,
    build_repositories,
    build_sqlite_repositories,
    reset_persistence,
    set_persistence,
)
from core.persistence.sqlite_watchlist import SqliteWatchlistRepository
from core.utils.watchlist_io import STATUS_HOLDING, STATUS_WATCHING


def _paths(tmp_path) -> PersistencePaths:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    return PersistencePaths(project_root=tmp_path, data_dir=data, output_dir=output)


def test_sqlite_watchlist_roundtrip_and_positions(tmp_path):
    paths = _paths(tmp_path)
    url = "sqlite:///:memory:"
    repos = build_sqlite_repositories(paths, database_url=url)
    assert isinstance(repos.watchlist, SqliteWatchlistRepository)

    items = [
        {"ticker": "7203.T", "status": STATUS_WATCHING},
        {"ticker": "8111.T", "status": STATUS_HOLDING, "shares": 50, "avg_price": 2000.0},
    ]
    repos.watchlist.save_all(items)

    loaded = repos.watchlist.load_all()
    assert len(loaded) == 2
    pos = repos.watchlist.get_positions()
    assert pos["8111.T"]["shares"] == 50
    assert pos["8111.T"]["avg_price"] == pytest.approx(2000.0)

    # JSON ミラー + import_from_json_file
    repos.watchlist.import_from_json_file()
    assert len(repos.watchlist.load_all()) == 2


def test_sqlite_portfolio_cash_yen(tmp_path):
    paths = _paths(tmp_path)
    repos = build_sqlite_repositories(paths, database_url="sqlite:///:memory:")
    repos.portfolio.set_cash_yen(2_400_000.7)
    assert repos.portfolio.get_cash_yen() == 2_400_000


def test_build_repositories_sqlite_backend(tmp_path, monkeypatch):
    reset_persistence()
    paths = _paths(tmp_path)
    monkeypatch.setenv("DPA_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("DPA_PERSISTENCE", "sqlite")
    bundle = build_repositories(paths)
    assert isinstance(bundle.watchlist, SqliteWatchlistRepository)
    bundle.portfolio.set_cash_yen(100)
    assert bundle.portfolio.get_cash_yen() == 100
    reset_persistence()


def test_get_persistence_default_file_backend():
    reset_persistence()
    from core.persistence.access import persistence_backend
    from core.persistence.file_watchlist import FileWatchlistRepository

    bundle = build_repositories(backend="file")
    set_persistence(bundle)
    assert persistence_backend() == "file"
    from core.persistence import get_persistence

    assert isinstance(get_persistence().watchlist, FileWatchlistRepository)
    reset_persistence()

"""プロセス内の PersistenceBundle アクセサ（DB-3）。"""
from __future__ import annotations

import os
from typing import Literal, Optional

from core.persistence.factory import (
    PersistenceBundle,
    build_file_repositories,
    build_sqlite_repositories,
)
from core.persistence.paths import PersistencePaths

Backend = Literal["file", "sqlite"]
_bundle: Optional[PersistenceBundle] = None


def persistence_backend() -> Backend:
    raw = os.environ.get("DPA_PERSISTENCE", "sqlite").strip().lower()
    if raw == "file":
        return "file"
    return "sqlite"


def build_repositories(
    paths: PersistencePaths | None = None,
    backend: Backend | None = None,
    database_url: str | None = None,
) -> PersistenceBundle:
    """永続化バックエンドに応じた Repository 一式を構築する。"""
    resolved_backend = backend or persistence_backend()
    if resolved_backend == "sqlite":
        return build_sqlite_repositories(paths, database_url=database_url)
    if resolved_backend == "file":
        return build_file_repositories(paths)
    raise ValueError(f"未対応の backend: {resolved_backend}")


def set_persistence(bundle: PersistenceBundle) -> None:
    """テストや DI 用にバンドルを差し替える。"""
    global _bundle
    _bundle = bundle


def reset_persistence() -> None:
    """シングルトンをクリアする（テストの teardown）。"""
    global _bundle
    _bundle = None


def get_persistence(paths: PersistencePaths | None = None) -> PersistenceBundle:
    """
    永続化バンドルを返す。初回は DPA_PERSISTENCE に従い構築する。
    paths を渡した場合はそのパスでバンドルを再構築する。
    """
    global _bundle
    if paths is not None:
        _bundle = build_repositories(paths)
        return _bundle
    if _bundle is None:
        _bundle = build_repositories()
    return _bundle


def sync_watchlist_from_json_file_if_sqlite() -> None:
    """SQLite モードで watchlist.json を DB に反映（update_holdings_bulk 後用）。"""
    from core.persistence.sqlite_watchlist import SqliteWatchlistRepository

    store = get_persistence()
    if isinstance(store.watchlist, SqliteWatchlistRepository):
        store.watchlist.import_from_json_file()

"""プロセス内の PersistenceBundle アクセサ（DB-3）。"""
from __future__ import annotations

import os
from typing import Literal, Optional

from core.persistence.factory import PersistenceBundle, build_file_repositories
from core.persistence.paths import PersistencePaths

_backend: Literal["file"] = "file"
_bundle: Optional[PersistenceBundle] = None


def build_repositories(
    paths: PersistencePaths | None = None,
    backend: Literal["file"] = "file",
) -> PersistenceBundle:
    """永続化バックエンドに応じた Repository 一式を構築する。"""
    if backend != "file":
        raise ValueError(f"未対応の backend: {backend}")
    _ = os.environ.get("DPA_PERSISTENCE", "file")
    return build_file_repositories(paths)


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
    永続化バンドルを返す。初回は File 実装をデフォルトパスで構築する。
    paths を渡した場合はそのパスでバンドルを再構築する。
    """
    global _bundle
    if paths is not None:
        _bundle = build_repositories(paths)
        return _bundle
    if _bundle is None:
        _bundle = build_repositories()
    return _bundle

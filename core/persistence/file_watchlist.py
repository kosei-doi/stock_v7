from __future__ import annotations

from core.persistence.paths import PersistencePaths
from core.utils.watchlist_io import (
    PositionEntry,
    WatchlistItem,
    load_watchlist,
    positions_from_watchlist,
    save_watchlist,
)


class FileWatchlistRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = str(paths.watchlist_path)

    def load_all(self) -> list[WatchlistItem]:
        return load_watchlist(self._path)

    def save_all(self, items: list[WatchlistItem]) -> None:
        save_watchlist(items, self._path)

    def get_positions(self) -> dict[str, PositionEntry]:
        return positions_from_watchlist(path=self._path)

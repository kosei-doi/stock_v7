from __future__ import annotations

from typing import Any

from core.dvc.data_fetcher import fetch_sector_peers_map
from core.persistence.json_io import write_json
from core.persistence.paths import PersistencePaths


class FileSectorPeersRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = paths.sector_peers_path

    def load(self) -> dict[str, Any]:
        return fetch_sector_peers_map(str(self._path))

    def save(self, data: dict[str, Any]) -> None:
        write_json(self._path, data)

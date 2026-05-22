from __future__ import annotations

from typing import Any, Optional

from core.persistence.json_io import write_json
from core.persistence.paths import PersistencePaths
from core.utils.daily_cache import load_cache


class FileMarketCacheRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = paths.daily_cache_path

    def load(self) -> Optional[dict[str, Any]]:
        return load_cache(str(self._path))

    def save(self, data: dict[str, Any]) -> None:
        write_json(self._path, data)

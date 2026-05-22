from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from core.persistence.json_io import read_json, write_json
from core.persistence.paths import PersistencePaths


class FileTickerAnalysisRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._output_dir = paths.output_dir

    def _path_for(self, ticker: str) -> Path:
        safe = ticker.strip()
        if not safe:
            raise ValueError("ticker is required")
        return self._output_dir / f"{safe}.json"

    def get(self, ticker: str) -> Optional[dict[str, Any]]:
        path = self._path_for(ticker)
        data = read_json(path, default=None)
        return data if isinstance(data, dict) else None

    def save(self, ticker: str, payload: dict[str, Any]) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        write_json(self._path_for(ticker), payload)

    def list_tickers(self) -> list[str]:
        if not self._output_dir.exists():
            return []
        return sorted(p.stem for p in self._output_dir.glob("*.json"))

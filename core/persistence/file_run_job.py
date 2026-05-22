from __future__ import annotations

from typing import Any, Optional

from core.persistence.json_io import read_json, write_json
from core.persistence.paths import PersistencePaths


class FileRunJobRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = paths.run_status_path

    def get_status(self) -> dict[str, Any]:
        data = read_json(self._path, default={})
        return data if isinstance(data, dict) else {}

    def update_status(
        self,
        status: str,
        message: str,
        step: Optional[int] = None,
        total_steps: int = 7,
        finished_at: Optional[str] = None,
    ) -> None:
        payload = {
            "status": status,
            "message": message,
            "step": step,
            "total_steps": total_steps,
            "finished_at": finished_at,
        }
        write_json(self._path, payload)

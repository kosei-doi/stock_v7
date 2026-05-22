from __future__ import annotations

from typing import Any, Optional

from core.persistence.json_io import read_json, write_json
from core.persistence.paths import PersistencePaths


class FileDailyReportRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._last = paths.last_report_path
        self._previous = paths.previous_report_path

    def get_last(self) -> Optional[dict[str, Any]]:
        data = read_json(self._last, default=None)
        return data if isinstance(data, dict) else None

    def get_previous(self) -> Optional[dict[str, Any]]:
        data = read_json(self._previous, default=None)
        return data if isinstance(data, dict) else None

    def save_last(self, report: dict[str, Any]) -> None:
        write_json(self._last, report)

    def save_previous(self, report: dict[str, Any]) -> None:
        write_json(self._previous, report)

    def rotate_previous(self, new_last: dict[str, Any]) -> None:
        current = self.get_last()
        if current:
            self.save_previous(current)
        self.save_last(new_last)

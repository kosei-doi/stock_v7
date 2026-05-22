from __future__ import annotations

from datetime import datetime, timedelta
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

    def save_last_with_date_rotation(self, new_report: dict[str, Any]) -> None:
        """
        日次レポートを last に保存。data_date が変わった場合のみ既存 last を previous へ退避。
        daily_routine の退避ロジックと同等。
        """
        self._last.parent.mkdir(parents=True, exist_ok=True)
        new_data_date = new_report.get("data_date")

        existing = self.get_last()
        if existing is not None:
            existing_data_date = existing.get("data_date")
            if existing_data_date != new_data_date:
                prev_data_date = existing_data_date
                prev_created_at = existing.get("created_at")
                if not prev_data_date and new_data_date:
                    try:
                        new_d = datetime.strptime(str(new_data_date), "%Y-%m-%d").date()
                        prev_data_date = (new_d - timedelta(days=1)).isoformat()
                    except (ValueError, TypeError):
                        prev_data_date = new_data_date
                if not prev_created_at:
                    prev_created_at = f"{prev_data_date} (前回実行)"
                out = dict(existing)
                out["created_at"] = prev_created_at
                out["data_date"] = prev_data_date
                self.save_previous(out)

        self.save_last(new_report)

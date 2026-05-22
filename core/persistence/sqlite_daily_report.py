from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import DailyReportRow
from core.persistence.paths import PersistencePaths

REPORT_KIND_LAST = "last"
REPORT_KIND_PREVIOUS = "previous"


class SqliteDailyReportRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def get_last(self) -> Optional[dict[str, Any]]:
        return self._get_kind(REPORT_KIND_LAST)

    def get_previous(self) -> Optional[dict[str, Any]]:
        return self._get_kind(REPORT_KIND_PREVIOUS)

    def save_last(self, report: dict[str, Any]) -> None:
        self._upsert_kind(REPORT_KIND_LAST, report)

    def save_previous(self, report: dict[str, Any]) -> None:
        self._upsert_kind(REPORT_KIND_PREVIOUS, report)

    def rotate_previous(self, new_last: dict[str, Any]) -> None:
        current = self.get_last()
        if current:
            self.save_previous(current)
        self.save_last(new_last)

    def save_last_with_date_rotation(self, new_report: dict[str, Any]) -> None:
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

    def _get_kind(self, kind: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(DailyReportRow, kind)
        if row is None:
            return None
        data = json.loads(row.payload_json)
        return data if isinstance(data, dict) else None

    def _upsert_kind(self, kind: str, report: dict[str, Any]) -> None:
        payload = json.dumps(report, ensure_ascii=False)
        data_date = report.get("data_date")
        if data_date is not None:
            data_date = str(data_date)
        stmt = sqlite_insert(DailyReportRow).values(
            report_kind=kind,
            payload_json=payload,
            data_date=data_date,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["report_kind"],
            set_={
                "payload_json": payload,
                "data_date": data_date,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

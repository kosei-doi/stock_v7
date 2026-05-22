from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from core.persistence.json_io import read_json, write_json
from core.persistence.paths import PersistencePaths


def _to_snapshot(date: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_date": date,
        "cash_yen": int(payload.get("cash_yen") or 0),
        "equity_value_yen": int(payload.get("equity_value_yen") or 0),
        "total_capital_yen": int(payload.get("total_capital_yen") or 0),
        "holdings": payload.get("holdings"),
        "source": str(payload.get("source") or "manual"),
        "updated_at": str(payload.get("updated_at") or datetime.now(timezone.utc).isoformat()),
    }


class FilePortfolioSnapshotRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = paths.portfolio_snapshots_path

    def _load_raw(self) -> dict[str, Any]:
        data = read_json(self._path, default={})
        return data if isinstance(data, dict) else {}

    def upsert(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        data = self._load_raw()
        date = str(snapshot.get("snapshot_date") or "")
        if not date:
            raise ValueError("snapshot_date が必要です")
        record = _to_snapshot(date, snapshot)
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        data[date] = record
        write_json(self._path, data)
        return record

    def list_all(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        data = self._load_raw()
        out: list[dict[str, Any]] = []
        for date, rec in data.items():
            if not isinstance(rec, dict):
                continue
            if from_date and date < from_date:
                continue
            if to_date and date > to_date:
                continue
            out.append({**rec, "snapshot_date": date})
        out.sort(key=lambda x: str(x.get("snapshot_date") or ""))
        return out

    def latest(self) -> Optional[dict[str, Any]]:
        all_ = self.list_all()
        return all_[-1] if all_ else None

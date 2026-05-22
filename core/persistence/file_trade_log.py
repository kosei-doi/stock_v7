from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.persistence.json_io import read_json, write_json
from core.persistence.paths import PersistencePaths


class FileTradeLogRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = paths.trade_log_path

    def _load_raw(self) -> list[dict[str, Any]]:
        data = read_json(self._path, default=[])
        return data if isinstance(data, list) else []

    def _next_id(self, items: list[dict[str, Any]]) -> int:
        max_id = 0
        for it in items:
            try:
                v = int(it.get("id") or 0)
                if v > max_id:
                    max_id = v
            except (TypeError, ValueError):
                continue
        return max_id + 1

    def add(self, entry: dict[str, Any]) -> dict[str, Any]:
        items = self._load_raw()
        record = dict(entry)
        record["id"] = self._next_id(items)
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        items.append(record)
        write_json(self._path, items)
        return record

    def list_all(
        self,
        ticker: Optional[str] = None,
        side: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        items = self._load_raw()
        out: list[dict[str, Any]] = []
        for it in items:
            if ticker and str(it.get("ticker") or "") != ticker:
                continue
            if side and str(it.get("side") or "").upper() != side.upper():
                continue
            d = str(it.get("trade_date") or "")
            if from_date and d < from_date:
                continue
            if to_date and d > to_date:
                continue
            out.append(it)
        out.sort(key=lambda x: (str(x.get("trade_date") or ""), int(x.get("id") or 0)), reverse=True)
        return out

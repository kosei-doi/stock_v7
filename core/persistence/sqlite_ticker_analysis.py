from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import TickerAnalysisRow
from core.persistence.paths import PersistencePaths


class SqliteTickerAnalysisRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._paths = paths
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def get(self, ticker: str) -> Optional[dict[str, Any]]:
        safe = ticker.strip()
        if not safe:
            return None
        with self._session_factory() as session:
            row = session.get(TickerAnalysisRow, safe)
        if row is None:
            return None
        data = json.loads(row.payload_json)
        return data if isinstance(data, dict) else None

    def save(self, ticker: str, payload: dict[str, Any]) -> None:
        safe = ticker.strip()
        if not safe:
            raise ValueError("ticker is required")
        payload_text = json.dumps(payload, ensure_ascii=False)
        updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        stmt = sqlite_insert(TickerAnalysisRow).values(
            ticker=safe,
            updated_at=updated_at,
            payload_json=payload_text,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker"],
            set_={"payload_json": payload_text, "updated_at": updated_at},
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

    def list_tickers(self) -> list[str]:
        with self._session_factory() as session:
            rows = session.scalars(select(TickerAnalysisRow.ticker)).all()
        return sorted(rows)

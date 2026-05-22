from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import MarketCacheRow
from core.persistence.paths import PersistencePaths

CACHE_KEY_MAIN = "main"


class SqliteMarketCacheRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def load(self) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(MarketCacheRow, CACHE_KEY_MAIN)
        if row is None:
            return None
        data = json.loads(row.payload_json)
        return data if isinstance(data, dict) else None

    def save(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        updated_date = data.get("updated_date")
        if updated_date is not None:
            updated_date = str(updated_date)
        stmt = sqlite_insert(MarketCacheRow).values(
            cache_key=CACHE_KEY_MAIN,
            payload_json=payload,
            updated_date=updated_date,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={"payload_json": payload, "updated_date": updated_date},
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

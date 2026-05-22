from __future__ import annotations

import json
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import SectorPeersRow
from core.persistence.paths import PersistencePaths

CACHE_KEY_DEFAULT = "default"


class SqliteSectorPeersRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def load(self) -> dict[str, Any]:
        with self._session_factory() as session:
            row = session.get(SectorPeersRow, CACHE_KEY_DEFAULT)
        if row is None:
            return {}
        data = json.loads(row.payload_json)
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        stmt = sqlite_insert(SectorPeersRow).values(
            cache_key=CACHE_KEY_DEFAULT,
            payload_json=payload,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["cache_key"],
            set_={"payload_json": payload},
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

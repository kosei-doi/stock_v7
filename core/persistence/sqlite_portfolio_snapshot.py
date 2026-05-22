from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import PortfolioSnapshotRow
from core.persistence.paths import PersistencePaths


class SqlitePortfolioSnapshotRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def upsert(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        date = str(snapshot.get("snapshot_date") or "")
        if not date:
            raise ValueError("snapshot_date が必要です")
        now = datetime.now(timezone.utc).isoformat()
        holdings = snapshot.get("holdings")
        holdings_json = json.dumps(holdings, ensure_ascii=False) if holdings is not None else None
        values = {
            "snapshot_date": date,
            "cash_yen": int(snapshot.get("cash_yen") or 0),
            "equity_value_yen": int(snapshot.get("equity_value_yen") or 0),
            "total_capital_yen": int(snapshot.get("total_capital_yen") or 0),
            "holdings_json": holdings_json,
            "source": str(snapshot.get("source") or "manual"),
            "updated_at": now,
        }
        with self._session_factory() as session:
            stmt = sqlite_insert(PortfolioSnapshotRow).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["snapshot_date"],
                set_={k: v for k, v in values.items() if k != "snapshot_date"},
            )
            session.execute(stmt)
            session.commit()
        return _decode(values)

    def list_all(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        stmt = select(PortfolioSnapshotRow)
        if from_date:
            stmt = stmt.where(PortfolioSnapshotRow.snapshot_date >= from_date)
        if to_date:
            stmt = stmt.where(PortfolioSnapshotRow.snapshot_date <= to_date)
        stmt = stmt.order_by(PortfolioSnapshotRow.snapshot_date.asc())
        with self._session_factory() as session:
            rows = session.scalars(stmt).all()
        return [_row_to_dict(r) for r in rows]

    def latest(self) -> Optional[dict[str, Any]]:
        stmt = select(PortfolioSnapshotRow).order_by(PortfolioSnapshotRow.snapshot_date.desc()).limit(1)
        with self._session_factory() as session:
            row = session.scalars(stmt).first()
        return _row_to_dict(row) if row else None


def _row_to_dict(r: PortfolioSnapshotRow) -> dict[str, Any]:
    holdings = None
    if r.holdings_json:
        try:
            holdings = json.loads(r.holdings_json)
        except (json.JSONDecodeError, TypeError):
            holdings = None
    return {
        "snapshot_date": r.snapshot_date,
        "cash_yen": r.cash_yen,
        "equity_value_yen": r.equity_value_yen,
        "total_capital_yen": r.total_capital_yen,
        "holdings": holdings,
        "source": r.source,
        "updated_at": r.updated_at,
    }


def _decode(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    raw = out.pop("holdings_json", None)
    if raw:
        try:
            out["holdings"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            out["holdings"] = None
    else:
        out["holdings"] = None
    return out

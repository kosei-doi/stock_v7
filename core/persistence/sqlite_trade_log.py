from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import TradeLogRow
from core.persistence.paths import PersistencePaths


class SqliteTradeLogRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def add(self, entry: dict[str, Any]) -> dict[str, Any]:
        created_at = str(entry.get("created_at") or datetime.now(timezone.utc).isoformat())
        with self._session_factory() as session:
            row = TradeLogRow(
                trade_date=str(entry.get("trade_date") or ""),
                side=str(entry.get("side") or "").upper(),
                ticker=str(entry.get("ticker") or ""),
                shares=int(entry.get("shares") or 0),
                price=float(entry.get("price") or 0.0),
                amount=int(entry.get("amount") or 0),
                avg_price_before=_float_or_none(entry.get("avg_price_before")),
                realized_pnl=_float_or_none(entry.get("realized_pnl")),
                note=entry.get("note"),
                created_at=created_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_dict(row)

    def list_all(
        self,
        ticker: Optional[str] = None,
        side: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        stmt = select(TradeLogRow)
        if ticker:
            stmt = stmt.where(TradeLogRow.ticker == ticker)
        if side:
            stmt = stmt.where(TradeLogRow.side == side.upper())
        if from_date:
            stmt = stmt.where(TradeLogRow.trade_date >= from_date)
        if to_date:
            stmt = stmt.where(TradeLogRow.trade_date <= to_date)
        stmt = stmt.order_by(TradeLogRow.trade_date.desc(), TradeLogRow.id.desc())
        with self._session_factory() as session:
            rows = session.scalars(stmt).all()
        return [_row_to_dict(r) for r in rows]


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _row_to_dict(r: TradeLogRow) -> dict[str, Any]:
    return {
        "id": r.id,
        "trade_date": r.trade_date,
        "side": r.side,
        "ticker": r.ticker,
        "shares": r.shares,
        "price": r.price,
        "amount": r.amount,
        "avg_price_before": r.avg_price_before,
        "realized_pnl": r.realized_pnl,
        "note": r.note,
        "created_at": r.created_at,
    }

from __future__ import annotations

from sqlalchemy import delete, select

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import WatchlistItemRow
from core.persistence.paths import PersistencePaths
from core.utils.money import yen_floor
from core.utils.watchlist_io import (
    STATUS_HOLDING,
    PositionEntry,
    WatchlistItem,
    load_watchlist,
)


class SqliteWatchlistRepository:
    """ウォッチリストの SQLite 実装。DB が唯一の SoT。"""

    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._paths = paths
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def load_all(self) -> list[WatchlistItem]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(WatchlistItemRow).order_by(WatchlistItemRow.sort_order)
            ).all()
        return [_row_to_item(r) for r in rows]

    def save_all(self, items: list[WatchlistItem]) -> None:
        self._persist_db(items)

    def import_from_json_file(self) -> None:
        """watchlist.json の内容を DB に取り込む（移行スクリプト用）。"""
        items = load_watchlist(str(self._paths.watchlist_path))
        self._persist_db(items)

    def get_positions(self) -> dict[str, PositionEntry]:
        positions: dict[str, PositionEntry] = {}
        for item in self.load_all():
            if (item.get("status") or "WATCHING") != STATUS_HOLDING:
                continue
            ticker = (item.get("ticker") or item.get("ticker_symbol") or "").strip()
            if not ticker:
                continue
            shares = item.get("shares") or item.get("shares_held") or 0
            try:
                shares = int(shares)
            except (TypeError, ValueError):
                shares = 0
            entry: PositionEntry = {"shares": shares}
            avg = item.get("avg_price")
            if avg is not None:
                try:
                    entry["avg_price"] = yen_floor(avg)
                except (TypeError, ValueError):
                    pass
            positions[ticker] = entry
        return positions

    def _persist_db(self, items: list[WatchlistItem]) -> None:
        with self._session_factory() as session:
            session.execute(delete(WatchlistItemRow))
            for idx, item in enumerate(items):
                ticker = (item.get("ticker") or item.get("ticker_symbol") or "").strip()
                if not ticker:
                    continue
                shares = item.get("shares") or item.get("shares_held")
                if shares is not None:
                    try:
                        shares = int(shares)
                    except (TypeError, ValueError):
                        shares = None
                avg = item.get("avg_price")
                if avg is not None:
                    try:
                        avg = float(yen_floor(avg))
                    except (TypeError, ValueError):
                        avg = None
                session.add(
                    WatchlistItemRow(
                        ticker=ticker,
                        status=item.get("status") or "WATCHING",
                        shares=shares,
                        avg_price=avg,
                        sort_order=idx,
                    )
                )
            session.commit()


def _row_to_item(row: WatchlistItemRow) -> WatchlistItem:
    item: WatchlistItem = {"ticker": row.ticker, "status": row.status}
    if row.shares is not None:
        item["shares"] = row.shares
    if row.avg_price is not None:
        item["avg_price"] = row.avg_price
    return item

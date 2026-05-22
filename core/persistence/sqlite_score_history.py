from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import ScoreHistoryEntryRow
from core.persistence.paths import PersistencePaths


class SqliteScoreHistoryRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def load_all(self) -> dict[str, Any]:
        with self._session_factory() as session:
            rows = session.scalars(select(ScoreHistoryEntryRow)).all()
        history: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            day = history.setdefault(row.logical_date, {})
            day[row.ticker] = {
                "total": row.total,
                "value": row.value,
                "safety": row.safety,
                "momentum": row.momentum,
            }
        return history

    def save_all(self, history: dict[str, Any]) -> None:
        with self._session_factory() as session:
            session.execute(delete(ScoreHistoryEntryRow))
            for logical_date, tickers in history.items():
                if not isinstance(tickers, dict):
                    continue
                for ticker, scores in tickers.items():
                    if not isinstance(scores, dict):
                        continue
                    session.add(
                        ScoreHistoryEntryRow(
                            logical_date=str(logical_date),
                            ticker=str(ticker),
                            total=_float_or_none(scores.get("total")),
                            value=_float_or_none(scores.get("value")),
                            safety=_float_or_none(scores.get("safety")),
                            momentum=_float_or_none(scores.get("momentum")),
                        )
                    )
            session.commit()

    def get_day(self, logical_date: str) -> dict[str, Any]:
        history = self.load_all()
        day = history.get(logical_date, {})
        return day if isinstance(day, dict) else {}

    def upsert_day(self, logical_date: str, ticker_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
        with self._session_factory() as session:
            for ticker, scores in ticker_scores.items():
                if not isinstance(scores, dict):
                    continue
                stmt = sqlite_insert(ScoreHistoryEntryRow).values(
                    logical_date=logical_date,
                    ticker=str(ticker),
                    total=_float_or_none(scores.get("total")),
                    value=_float_or_none(scores.get("value")),
                    safety=_float_or_none(scores.get("safety")),
                    momentum=_float_or_none(scores.get("momentum")),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["logical_date", "ticker"],
                    set_={
                        "total": _float_or_none(scores.get("total")),
                        "value": _float_or_none(scores.get("value")),
                        "safety": _float_or_none(scores.get("safety")),
                        "momentum": _float_or_none(scores.get("momentum")),
                    },
                )
                session.execute(stmt)
            session.commit()
        return self.load_all()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

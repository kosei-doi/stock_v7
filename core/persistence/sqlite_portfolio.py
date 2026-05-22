from __future__ import annotations

from datetime import datetime, timezone

from core.persistence.db import PORTFOLIO_STATE_ROW_ID, get_session_factory, resolve_database_url
from core.persistence.models import PortfolioStateRow
from core.persistence.paths import PersistencePaths
from core.utils.money import yen_floor


class SqlitePortfolioRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._paths = paths
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def get_cash_yen(self) -> int:
        with self._session_factory() as session:
            row = session.get(PortfolioStateRow, PORTFOLIO_STATE_ROW_ID)
            if row is None:
                return 0
            return int(row.cash_yen)

    def set_cash_yen(self, cash_yen: int | float) -> None:
        value = yen_floor(cash_yen)
        now = datetime.now(timezone.utc).isoformat()
        with self._session_factory() as session:
            row = session.get(PortfolioStateRow, PORTFOLIO_STATE_ROW_ID)
            if row is None:
                session.add(
                    PortfolioStateRow(
                        id=PORTFOLIO_STATE_ROW_ID,
                        cash_yen=value,
                        updated_at=now,
                    )
                )
            else:
                row.cash_yen = value
                row.updated_at = now
            session.commit()

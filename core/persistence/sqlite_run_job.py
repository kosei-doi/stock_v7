from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.persistence.db import get_session_factory, resolve_database_url
from core.persistence.models import RunJobRow
from core.persistence.paths import PersistencePaths

JOB_NAME_DAILY_BATCH = "daily_batch"


class SqliteRunJobRepository:
    def __init__(self, paths: PersistencePaths, database_url: str | None = None) -> None:
        self._database_url = database_url or resolve_database_url(paths)
        self._session_factory = get_session_factory(self._database_url)

    def get_status(self) -> dict[str, Any]:
        with self._session_factory() as session:
            row = session.get(RunJobRow, JOB_NAME_DAILY_BATCH)
        if row is None:
            return {}
        return {
            "status": row.status,
            "message": row.message or "",
            "step": row.step,
            "total_steps": row.total_steps if row.total_steps is not None else 7,
            "finished_at": row.finished_at,
        }

    def update_status(
        self,
        status: str,
        message: str,
        step: Optional[int] = None,
        total_steps: int = 7,
        finished_at: Optional[str] = None,
    ) -> None:
        stmt = sqlite_insert(RunJobRow).values(
            job_name=JOB_NAME_DAILY_BATCH,
            status=status,
            message=message,
            step=step,
            total_steps=total_steps,
            finished_at=finished_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["job_name"],
            set_={
                "status": status,
                "message": message,
                "step": step,
                "total_steps": total_steps,
                "finished_at": finished_at,
            },
        )
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()

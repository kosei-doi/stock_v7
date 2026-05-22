"""SQLite エンジン・セッション（DB-3 フェーズ B）。"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.persistence.models import Base
from core.persistence.paths import PersistencePaths

PORTFOLIO_STATE_ROW_ID = 1


def resolve_database_url(paths: PersistencePaths | None = None) -> str:
    """DPA_DATABASE_URL または data_dir/dpa.db から接続 URL を決定する。"""
    explicit = os.environ.get("DPA_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    resolved = paths or PersistencePaths.from_project_root()
    db_path = (resolved.data_dir / "dpa.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


@lru_cache(maxsize=8)
def get_engine(database_url: str) -> Engine:
    connect_args: dict = {}
    engine_kwargs: dict = {"future": True}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args
        if ":memory:" in database_url:
            engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_kwargs)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


@lru_cache(maxsize=8)
def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = get_engine(database_url)
    init_db(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

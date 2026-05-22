"""SQLAlchemy ORM models（ADR-001）。"""
from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WatchlistItemRow(Base):
    __tablename__ = "watchlist_items"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="WATCHING")
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="(datetime('now'))"
    )


class PortfolioStateRow(Base):
    __tablename__ = "portfolio_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cash_yen: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="(datetime('now'))"
    )


class DailyReportRow(Base):
    __tablename__ = "daily_reports"

    report_kind: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    data_date: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="(datetime('now'))"
    )


class ScoreHistoryEntryRow(Base):
    __tablename__ = "score_history_entries"

    logical_date: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum: Mapped[float | None] = mapped_column(Float, nullable=True)


class RunJobRow(Base):
    __tablename__ = "run_jobs"

    job_name: Mapped[str] = mapped_column(String, primary_key=True, default="daily_batch")
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)

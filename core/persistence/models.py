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

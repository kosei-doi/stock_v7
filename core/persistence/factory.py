from __future__ import annotations

from dataclasses import dataclass

from core.persistence.file_daily_report import FileDailyReportRepository
from core.persistence.file_market_cache import FileMarketCacheRepository
from core.persistence.file_portfolio import FilePortfolioRepository
from core.persistence.file_run_job import FileRunJobRepository
from core.persistence.file_score_history import FileScoreHistoryRepository
from core.persistence.file_sector_peers import FileSectorPeersRepository
from core.persistence.file_ticker_analysis import FileTickerAnalysisRepository
from core.persistence.file_watchlist import FileWatchlistRepository
from core.persistence.paths import PersistencePaths
from core.persistence.protocols import (
    DailyReportRepository,
    MarketCacheRepository,
    PortfolioRepository,
    RunJobRepository,
    ScoreHistoryRepository,
    SectorPeersRepository,
    TickerAnalysisRepository,
    WatchlistRepository,
)
from core.persistence.sqlite_portfolio import SqlitePortfolioRepository
from core.persistence.sqlite_watchlist import SqliteWatchlistRepository


@dataclass(frozen=True)
class PersistenceBundle:
    paths: PersistencePaths
    watchlist: WatchlistRepository
    portfolio: PortfolioRepository
    daily_report: DailyReportRepository
    score_history: ScoreHistoryRepository
    run_job: RunJobRepository
    market_cache: MarketCacheRepository
    sector_peers: SectorPeersRepository
    ticker_analysis: TickerAnalysisRepository


def build_file_repositories(paths: PersistencePaths | None = None) -> PersistenceBundle:
    """File ベースの Repository 一式を構築する。"""
    resolved = paths or PersistencePaths.from_project_root()
    return PersistenceBundle(
        paths=resolved,
        watchlist=FileWatchlistRepository(resolved),
        portfolio=FilePortfolioRepository(resolved),
        daily_report=FileDailyReportRepository(resolved),
        score_history=FileScoreHistoryRepository(resolved),
        run_job=FileRunJobRepository(resolved),
        market_cache=FileMarketCacheRepository(resolved),
        sector_peers=FileSectorPeersRepository(resolved),
        ticker_analysis=FileTickerAnalysisRepository(resolved),
    )


def build_sqlite_repositories(
    paths: PersistencePaths | None = None,
    database_url: str | None = None,
) -> PersistenceBundle:
    """SQLite watchlist/portfolio + File でその他を構築する。"""
    from core.persistence.db import resolve_database_url

    resolved = paths or PersistencePaths.from_project_root()
    url = database_url or resolve_database_url(resolved)
    return PersistenceBundle(
        paths=resolved,
        watchlist=SqliteWatchlistRepository(resolved, url),
        portfolio=SqlitePortfolioRepository(resolved, url),
        daily_report=FileDailyReportRepository(resolved),
        score_history=FileScoreHistoryRepository(resolved),
        run_job=FileRunJobRepository(resolved),
        market_cache=FileMarketCacheRepository(resolved),
        sector_peers=FileSectorPeersRepository(resolved),
        ticker_analysis=FileTickerAnalysisRepository(resolved),
    )

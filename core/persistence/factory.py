from __future__ import annotations

from dataclasses import dataclass

from core.persistence.file_daily_report import FileDailyReportRepository
from core.persistence.file_market_cache import FileMarketCacheRepository
from core.persistence.file_portfolio import FilePortfolioRepository
from core.persistence.file_portfolio_snapshot import FilePortfolioSnapshotRepository
from core.persistence.file_run_job import FileRunJobRepository
from core.persistence.file_score_history import FileScoreHistoryRepository
from core.persistence.file_sector_peers import FileSectorPeersRepository
from core.persistence.file_ticker_analysis import FileTickerAnalysisRepository
from core.persistence.file_trade_log import FileTradeLogRepository
from core.persistence.file_watchlist import FileWatchlistRepository
from core.persistence.paths import PersistencePaths
from core.persistence.protocols import (
    DailyReportRepository,
    MarketCacheRepository,
    PortfolioRepository,
    PortfolioSnapshotRepository,
    RunJobRepository,
    ScoreHistoryRepository,
    SectorPeersRepository,
    TickerAnalysisRepository,
    TradeLogRepository,
    WatchlistRepository,
)
from core.persistence.sqlite_daily_report import SqliteDailyReportRepository
from core.persistence.sqlite_market_cache import SqliteMarketCacheRepository
from core.persistence.sqlite_portfolio import SqlitePortfolioRepository
from core.persistence.sqlite_portfolio_snapshot import SqlitePortfolioSnapshotRepository
from core.persistence.sqlite_run_job import SqliteRunJobRepository
from core.persistence.sqlite_score_history import SqliteScoreHistoryRepository
from core.persistence.sqlite_sector_peers import SqliteSectorPeersRepository
from core.persistence.sqlite_ticker_analysis import SqliteTickerAnalysisRepository
from core.persistence.sqlite_trade_log import SqliteTradeLogRepository
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
    trade_log: TradeLogRepository
    portfolio_snapshot: PortfolioSnapshotRepository


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
        trade_log=FileTradeLogRepository(resolved),
        portfolio_snapshot=FilePortfolioSnapshotRepository(resolved),
    )


def build_sqlite_repositories(
    paths: PersistencePaths | None = None,
    database_url: str | None = None,
) -> PersistenceBundle:
    """SQLite: 全 Repository を DB に構築する。"""
    from core.persistence.db import resolve_database_url

    resolved = paths or PersistencePaths.from_project_root()
    url = database_url or resolve_database_url(resolved)
    return PersistenceBundle(
        paths=resolved,
        watchlist=SqliteWatchlistRepository(resolved, url),
        portfolio=SqlitePortfolioRepository(resolved, url),
        daily_report=SqliteDailyReportRepository(resolved, url),
        score_history=SqliteScoreHistoryRepository(resolved, url),
        run_job=SqliteRunJobRepository(resolved, url),
        market_cache=SqliteMarketCacheRepository(resolved, url),
        sector_peers=SqliteSectorPeersRepository(resolved, url),
        ticker_analysis=SqliteTickerAnalysisRepository(resolved, url),
        trade_log=SqliteTradeLogRepository(resolved, url),
        portfolio_snapshot=SqlitePortfolioSnapshotRepository(resolved, url),
    )

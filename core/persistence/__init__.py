"""永続化 Repository 層（DB-2: File 実装）。"""
from core.persistence.access import (
    build_repositories,
    get_persistence,
    persistence_backend,
    reset_persistence,
    set_persistence,
    sync_watchlist_from_json_file_if_sqlite,
)
from core.persistence.factory import (
    PersistenceBundle,
    build_file_repositories,
    build_sqlite_repositories,
)
from core.persistence.paths import PersistencePaths, default_project_root
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

__all__ = [
    "PersistenceBundle",
    "PersistencePaths",
    "build_file_repositories",
    "build_repositories",
    "build_sqlite_repositories",
    "get_persistence",
    "persistence_backend",
    "reset_persistence",
    "set_persistence",
    "sync_watchlist_from_json_file_if_sqlite",
    "default_project_root",
    "WatchlistRepository",
    "PortfolioRepository",
    "DailyReportRepository",
    "ScoreHistoryRepository",
    "RunJobRepository",
    "MarketCacheRepository",
    "SectorPeersRepository",
    "TickerAnalysisRepository",
    "TradeLogRepository",
    "PortfolioSnapshotRepository",
]

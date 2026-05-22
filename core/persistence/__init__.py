"""永続化 Repository 層（DB-2: File 実装）。"""
from core.persistence.access import (
    build_repositories,
    get_persistence,
    reset_persistence,
    set_persistence,
)
from core.persistence.factory import PersistenceBundle, build_file_repositories
from core.persistence.paths import PersistencePaths, default_project_root
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

__all__ = [
    "PersistenceBundle",
    "PersistencePaths",
    "build_file_repositories",
    "build_repositories",
    "get_persistence",
    "reset_persistence",
    "set_persistence",
    "default_project_root",
    "WatchlistRepository",
    "PortfolioRepository",
    "DailyReportRepository",
    "ScoreHistoryRepository",
    "RunJobRepository",
    "MarketCacheRepository",
    "SectorPeersRepository",
    "TickerAnalysisRepository",
]

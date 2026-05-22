"""永続化 Repository 層（DB-2: File 実装）。"""
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

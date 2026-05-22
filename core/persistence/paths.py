"""永続化レイヤのパス解決。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def default_project_root() -> Path:
    """リポジトリルート（core/persistence の 2 階層上）。"""
    return Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class PersistencePaths:
    project_root: Path
    data_dir: Path
    output_dir: Path

    @classmethod
    def from_project_root(cls, project_root: Path | None = None) -> PersistencePaths:
        root = (project_root or default_project_root()).resolve()
        return cls(
            project_root=root,
            data_dir=root / "data",
            output_dir=root / "output",
        )

    @property
    def watchlist_path(self) -> Path:
        return self.data_dir / "watchlist.json"

    @property
    def portfolio_path(self) -> Path:
        return self.project_root / "portfolio_state.json"

    @property
    def last_report_path(self) -> Path:
        return self.data_dir / "last_report.json"

    @property
    def previous_report_path(self) -> Path:
        return self.data_dir / "previous_report.json"

    @property
    def scores_history_path(self) -> Path:
        return self.data_dir / "scores_history.json"

    @property
    def run_status_path(self) -> Path:
        return self.data_dir / "run_status.json"

    @property
    def daily_cache_path(self) -> Path:
        return self.data_dir / "daily_cache.json"

    @property
    def sector_peers_path(self) -> Path:
        return self.data_dir / "sector_peers.json"

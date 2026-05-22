from __future__ import annotations

from typing import Any

from core.dpa.dpa_scores import load_scores_history, save_scores_history
from core.persistence.paths import PersistencePaths


class FileScoreHistoryRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = str(paths.scores_history_path)

    def load_all(self) -> dict[str, Any]:
        return load_scores_history(self._path)

    def save_all(self, history: dict[str, Any]) -> None:
        save_scores_history(history, self._path)

    def get_day(self, logical_date: str) -> dict[str, Any]:
        history = self.load_all()
        day = history.get(logical_date, {})
        return day if isinstance(day, dict) else {}

    def upsert_day(self, logical_date: str, ticker_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
        history = self.load_all()
        history[logical_date] = ticker_scores
        self.save_all(history)
        return history

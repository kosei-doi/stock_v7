from __future__ import annotations

from core.persistence.json_io import read_json, write_json
from core.persistence.paths import PersistencePaths
from core.utils.money import yen_floor


class FilePortfolioRepository:
    def __init__(self, paths: PersistencePaths) -> None:
        self._path = paths.portfolio_path

    def get_cash_yen(self) -> int:
        state = read_json(self._path, default={})
        if not isinstance(state, dict):
            return 0
        return yen_floor(state.get("cash_yen", 0))

    def set_cash_yen(self, cash_yen: int | float) -> None:
        write_json(self._path, {"cash_yen": yen_floor(cash_yen)})

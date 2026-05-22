#!/usr/bin/env python3
"""
JSON ソースと SQLite (dpa.db) の件数・主要フィールドを照合する（DB-8）。

import 直後または本番切替前に実行する。

  python scripts/verify_db_migration.py --data-dir /opt/dpa_app
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.persistence.factory import build_sqlite_repositories
from core.persistence.paths import PersistencePaths

from scripts.migrate_json_to_db import _collect_sources, _log, _score_history_row_count


def _compare(paths: PersistencePaths, database_url: str) -> list[str]:
    sources = _collect_sources(paths)
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        db_file = Path(database_url.replace("sqlite:///", ""))
        if not db_file.exists():
            return [f"DB ファイルが存在しません: {db_file}"]

    repos = build_sqlite_repositories(paths, database_url=database_url)
    errors: list[str] = []

    wl_json = len(sources["watchlist"])
    wl_db = len(repos.watchlist.load_all())
    if wl_json != wl_db:
        errors.append(f"watchlist 件数: JSON={wl_json} DB={wl_db}")

    portfolio = sources["portfolio"]
    cash_json = portfolio.get("cash_yen") if isinstance(portfolio, dict) else None
    cash_db = repos.portfolio.get_cash_yen()
    if cash_json is not None and int(cash_json) != cash_db:
        errors.append(f"portfolio cash_yen: JSON={cash_json} DB={cash_db}")

    last_report = sources["last_report"]
    data_date_json = (last_report or {}).get("data_date") if isinstance(last_report, dict) else None
    lr_db = repos.daily_report.get_last()
    data_date_db = (lr_db or {}).get("data_date")
    if data_date_json is not None and data_date_json != data_date_db:
        errors.append(f"last_report data_date: JSON={data_date_json} DB={data_date_db}")

    prev_report = sources["previous_report"]
    if isinstance(prev_report, dict) and prev_report:
        prev_db = repos.daily_report.get_previous()
        if not prev_db:
            errors.append("previous_report: JSON にあるが DB に無い")

    sh_json = _score_history_row_count(sources["scores_history"])
    sh_db = _score_history_row_count(repos.score_history.load_all())
    if sh_json != sh_db:
        errors.append(f"score_history 行数: JSON={sh_json} DB={sh_db}")

    out_json = len(sources["output_files"])
    out_db = len(repos.ticker_analysis.list_tickers())
    if out_json != out_db:
        errors.append(f"ticker_analyses 件数: JSON(output)={out_json} DB={out_db}")

    if sources["daily_cache"] and repos.market_cache.load() is None:
        errors.append("daily_cache: JSON にあるが DB market_cache が空")

    if sources["sector_peers"] and not repos.sector_peers.load():
        errors.append("sector_peers: JSON にあるが DB が空")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JSON と SQLite の整合検証（DB-8）")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)

    project_root = args.data_dir.resolve()
    paths = PersistencePaths(
        project_root=project_root,
        data_dir=project_root / "data",
        output_dir=project_root / "output",
    )
    db_url = args.database_url
    if db_url is None:
        db_url = f"sqlite:///{(paths.data_dir / 'dpa.db').resolve()}"

    _log(f"検証: {project_root}")
    _log(f"DB: {db_url}")

    errors = _compare(paths, db_url)
    if errors:
        _log("--- 不一致 ---")
        for e in errors:
            _log(f"  ERROR: {e}")
        return 1

    _log("--- OK: JSON と DB の主要項目は一致しています ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
既存 JSON ファイルを SQLite (data/dpa.db) にインポートする（DB-6）。

用法:
  python scripts/migrate_json_to_db.py --data-dir /path/to/project [--dry-run] [--archive-json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# リポジトリルートを sys.path に追加
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.persistence.access import set_persistence
from core.persistence.factory import build_sqlite_repositories
from core.persistence.json_io import read_json
from core.persistence.paths import PersistencePaths
from core.persistence.sqlite_watchlist import SqliteWatchlistRepository
from core.utils.watchlist_io import load_watchlist


def _score_history_row_count(history: dict) -> int:
    n = 0
    for tickers in history.values():
        if isinstance(tickers, dict):
            n += len(tickers)
    return n


def _read_optional(path: Path) -> dict | list | None:
    data = read_json(path, default=None)
    return data


def _log(msg: str) -> None:
    print(msg, flush=True)


def _collect_sources(paths: PersistencePaths) -> dict:
    wl_path = paths.watchlist_path
    wl = load_watchlist(str(wl_path)) if wl_path.exists() else []

    portfolio_path = paths.portfolio_path
    portfolio = _read_optional(portfolio_path) or {}

    last_report = _read_optional(paths.last_report_path)
    previous_report = _read_optional(paths.previous_report_path)
    scores_history = _read_optional(paths.scores_history_path) or {}
    if not isinstance(scores_history, dict):
        scores_history = {}

    run_status = _read_optional(paths.run_status_path) or {}
    if not isinstance(run_status, dict):
        run_status = {}

    daily_cache = _read_optional(paths.daily_cache_path)
    sector_peers = _read_optional(paths.sector_peers_path) or {}
    if not isinstance(sector_peers, dict):
        sector_peers = {}

    output_files = sorted(paths.output_dir.glob("*.json")) if paths.output_dir.exists() else []

    return {
        "watchlist": wl,
        "portfolio": portfolio,
        "last_report": last_report,
        "previous_report": previous_report,
        "scores_history": scores_history,
        "run_status": run_status,
        "daily_cache": daily_cache,
        "sector_peers": sector_peers,
        "output_files": output_files,
    }


def _print_verification(paths: PersistencePaths, sources: dict, repos=None) -> None:
    wl = sources["watchlist"]
    portfolio = sources["portfolio"]
    last_report = sources["last_report"]
    scores_history = sources["scores_history"]
    output_files = sources["output_files"]

    _log("--- 検証（import 元 JSON）---")
    _log(f"  watchlist 件数: {len(wl)}")
    cash = portfolio.get("cash_yen") if isinstance(portfolio, dict) else None
    _log(f"  portfolio cash_yen: {cash}")
    data_date = (last_report or {}).get("data_date") if isinstance(last_report, dict) else None
    _log(f"  last_report data_date: {data_date}")
    _log(f"  score_history 行数（日付×銘柄）: {_score_history_row_count(scores_history)}")
    _log(f"  output/*.json 件数: {len(output_files)}")
    if sources["daily_cache"]:
        size = paths.daily_cache_path.stat().st_size if paths.daily_cache_path.exists() else 0
        _log(f"  daily_cache.json: あり ({size:,} bytes)")
    else:
        _log("  daily_cache.json: なし（スキップ可）")

    if repos is not None:
        _log("--- 検証（DB 読み戻し）---")
        _log(f"  watchlist DB 件数: {len(repos.watchlist.load_all())}")
        _log(f"  portfolio cash_yen DB: {repos.portfolio.get_cash_yen()}")
        lr = repos.daily_report.get_last()
        _log(f"  daily_reports.last data_date: {(lr or {}).get('data_date')}")
        db_scores = repos.score_history.load_all()
        _log(f"  score_history DB 行数: {_score_history_row_count(db_scores)}")
        _log(f"  ticker_analyses DB 件数: {len(repos.ticker_analysis.list_tickers())}")


def _import_all(paths: PersistencePaths, sources: dict, database_url: str):
    repos = build_sqlite_repositories(paths, database_url=database_url)
    set_persistence(repos)

    if sources["watchlist"] and paths.watchlist_path.exists():
        if isinstance(repos.watchlist, SqliteWatchlistRepository):
            repos.watchlist.import_from_json_file()
        else:
            repos.watchlist.save_all(sources["watchlist"])

    portfolio = sources["portfolio"]
    if isinstance(portfolio, dict) and "cash_yen" in portfolio:
        repos.portfolio.set_cash_yen(portfolio["cash_yen"])

    last_report = sources["last_report"]
    if isinstance(last_report, dict):
        repos.daily_report.save_last(last_report)

    previous_report = sources["previous_report"]
    if isinstance(previous_report, dict):
        repos.daily_report.save_previous(previous_report)

    scores_history = sources["scores_history"]
    if scores_history:
        repos.score_history.save_all(scores_history)

    run_status = sources["run_status"]
    if run_status:
        repos.run_job.update_status(
            status=str(run_status.get("status", "idle")),
            message=str(run_status.get("message", "")),
            step=run_status.get("step"),
            total_steps=int(run_status.get("total_steps", 7)),
            finished_at=run_status.get("finished_at"),
        )

    daily_cache = sources["daily_cache"]
    if isinstance(daily_cache, dict):
        repos.market_cache.save(daily_cache)

    sector_peers = sources["sector_peers"]
    if sector_peers:
        repos.sector_peers.save(sector_peers)

    for op_path in sources["output_files"]:
        ticker = op_path.stem
        data = read_json(op_path, default=None)
        if isinstance(data, dict):
            repos.ticker_analysis.save(ticker, data)

    return repos


def _archive_json(paths: PersistencePaths) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_data = paths.data_dir.parent / f"data.json.bak.{stamp}"
    if paths.data_dir.exists():
        shutil.copytree(paths.data_dir, bak_data, dirs_exist_ok=False)
        _log(f"  data/ を退避: {bak_data}")
    if paths.output_dir.exists():
        bak_output = paths.project_root / f"output.bak.{stamp}"
        shutil.copytree(paths.output_dir, bak_output, dirs_exist_ok=False)
        _log(f"  output/ を退避: {bak_output}")
    portfolio = paths.portfolio_path
    if portfolio.exists():
        shutil.copy2(portfolio, portfolio.with_suffix(portfolio.suffix + f".bak.{stamp}"))
        _log(f"  portfolio_state.json を退避")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JSON → SQLite ワンショット import（DB-6）")
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="プロジェクトルート（本番: /opt/dpa_app）",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="省略時は <data-dir>/data/dpa.db",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="読み取り・件数ログのみ（DB 書き込みなし）",
    )
    parser.add_argument(
        "--archive-json",
        action="store_true",
        help="import 成功後に data/・output/・portfolio_state.json を .bak へ退避",
    )
    args = parser.parse_args(argv)

    project_root = args.data_dir.resolve()
    if not project_root.is_dir():
        _log(f"エラー: --data-dir が存在しません: {project_root}")
        return 1

    paths = PersistencePaths(
        project_root=project_root,
        data_dir=project_root / "data",
        output_dir=project_root / "output",
    )

    db_url = args.database_url
    if db_url is None:
        paths.data_dir.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{(paths.data_dir / 'dpa.db').resolve()}"

    _log(f"プロジェクト: {project_root}")
    _log(f"DB URL: {db_url}")
    _log(f"モード: {'dry-run' if args.dry_run else 'import'}")

    sources = _collect_sources(paths)
    _print_verification(paths, sources)

    if args.dry_run:
        _log("dry-run のため DB への書き込みは行いません。")
        return 0

    try:
        repos = _import_all(paths, sources, db_url)
    except Exception as e:
        _log(f"import 失敗: {e}")
        return 1

    _print_verification(paths, sources, repos=repos)

    if args.archive_json:
        _archive_json(paths)
        _log("JSON 退避完了。DPA_PERSISTENCE=sqlite で再起動してください。")
    else:
        _log("import 完了（JSON 退避なし）。本番切替時は --archive-json を検討してください。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""File Repository 層のスモークテスト（DB-2）。"""
from __future__ import annotations

import pytest

from core.persistence import PersistencePaths, build_file_repositories
from core.utils.watchlist_io import (
    STATUS_HOLDING,
    STATUS_WATCHING,
    load_watchlist,
    positions_from_watchlist,
    save_watchlist,
)


def _paths(tmp_path) -> PersistencePaths:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    return PersistencePaths(project_root=tmp_path, data_dir=data, output_dir=output)


def test_watchlist_roundtrip_matches_direct_io(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    items = [
        {"ticker": "7203.T", "status": STATUS_WATCHING},
        {"ticker": "8111.T", "status": STATUS_HOLDING, "shares": 100, "avg_price": 2000.0},
    ]
    repos.watchlist.save_all(items)

    loaded = repos.watchlist.load_all()
    assert len(loaded) == 2
    direct = load_watchlist(str(paths.watchlist_path))
    assert direct == loaded

    pos_repo = repos.watchlist.get_positions()
    pos_direct = positions_from_watchlist(path=str(paths.watchlist_path))
    assert pos_repo == pos_direct
    assert pos_repo["8111.T"]["shares"] == 100


def test_portfolio_cash_yen_integer(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    repos.portfolio.set_cash_yen(2_400_000.9)
    assert repos.portfolio.get_cash_yen() == 2_400_000


def test_daily_report_rotate_previous(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    old = {"data_date": "2026-05-21", "phase": "caution"}
    repos.daily_report.save_last(old)
    new = {"data_date": "2026-05-22", "phase": "panic"}
    repos.daily_report.rotate_previous(new)

    assert repos.daily_report.get_previous() == old
    assert repos.daily_report.get_last() == new


def test_score_history_upsert_day(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    repos.score_history.upsert_day(
        "2026-05-22",
        {"7203.T": {"total": 70.0, "value": 60.0, "safety": 80.0, "momentum": 50.0}},
    )
    history = repos.score_history.load_all()
    assert "2026-05-22" in history
    assert history["2026-05-22"]["7203.T"]["total"] == pytest.approx(70.0)
    assert repos.score_history.get_day("2026-05-22")["7203.T"]["total"] == pytest.approx(70.0)


def test_run_job_update_status(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    repos.run_job.update_status("running", "step 1", step=1, total_steps=7)
    status = repos.run_job.get_status()
    assert status["status"] == "running"
    assert status["message"] == "step 1"
    assert status["step"] == 1
    assert status["total_steps"] == 7


def test_ticker_analysis_save_get_list(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    payload = {"ticker": "7203.T", "name": "Toyota", "scores": {"total_score": 65.0}}
    repos.ticker_analysis.save("7203.T", payload)
    assert repos.ticker_analysis.get("7203.T") == payload
    assert "7203.T" in repos.ticker_analysis.list_tickers()


def test_market_cache_save_load(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    data = {"updated_date": "2026-05-22", "benchmark_ticker": "1306.T"}
    repos.market_cache.save(data)
    loaded = repos.market_cache.load()
    assert loaded == data


def test_sector_peers_save_load(tmp_path):
    paths = _paths(tmp_path)
    repos = build_file_repositories(paths)
    data = {"Technology": ["6758.T", "6501.T"]}
    repos.sector_peers.save(data)
    assert repos.sector_peers.load() == data


def test_build_file_repositories_default_paths():
    bundle = build_file_repositories()
    assert bundle.paths.project_root.name  # non-empty root
    assert bundle.watchlist is not None
    assert bundle.portfolio is not None

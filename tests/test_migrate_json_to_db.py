"""migrate_json_to_db.py のスモークテスト（DB-6）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.persistence import PersistencePaths, build_sqlite_repositories
from core.persistence.json_io import read_json
from scripts import migrate_json_to_db as migrate


def _minimal_project(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    (data / "watchlist.json").write_text(
        json.dumps([{"ticker": "7203.T", "status": "WATCHING"}]),
        encoding="utf-8",
    )
    (tmp_path / "portfolio_state.json").write_text(
        json.dumps({"cash_yen": 1_500_000}),
        encoding="utf-8",
    )
    (data / "last_report.json").write_text(
        json.dumps({"data_date": "2026-05-22", "cash_yen": 1_500_000}),
        encoding="utf-8",
    )
    (data / "scores_history.json").write_text(
        json.dumps(
            {
                "2026-05-22": {
                    "7203.T": {"total": 70.0, "value": 60.0, "safety": 80.0, "momentum": 50.0}
                }
            }
        ),
        encoding="utf-8",
    )
    (data / "run_status.json").write_text(
        json.dumps({"status": "idle", "message": "", "step": None, "total_steps": 7}),
        encoding="utf-8",
    )
    (data / "sector_peers.json").write_text(json.dumps({"Auto": ["7203.T"]}), encoding="utf-8")
    (output / "7203.T.json").write_text(
        json.dumps({"ticker": "7203.T", "scores": {"total_score": 70.0}}),
        encoding="utf-8",
    )
    return tmp_path


def test_migrate_dry_run_counts(tmp_path):
    root = _minimal_project(tmp_path)
    assert migrate.main(["--data-dir", str(root), "--dry-run"]) == 0


def test_migrate_imports_to_memory_db(tmp_path):
    root = _minimal_project(tmp_path)
    db_url = "sqlite:///:memory:"
    assert migrate.main(["--data-dir", str(root), "--database-url", db_url]) == 0

    paths = PersistencePaths(
        project_root=root,
        data_dir=root / "data",
        output_dir=root / "output",
    )
    repos = build_sqlite_repositories(paths, database_url=db_url)
    assert len(repos.watchlist.load_all()) == 1
    assert repos.portfolio.get_cash_yen() == 1_500_000
    assert repos.daily_report.get_last()["data_date"] == "2026-05-22"
    assert repos.ticker_analysis.get("7203.T") is not None
    history = repos.score_history.load_all()
    assert history["2026-05-22"]["7203.T"]["total"] == pytest.approx(70.0)


def test_migrate_archive_json(tmp_path):
    root = _minimal_project(tmp_path)
    db_path = root / "data" / "dpa.db"
    assert migrate.main(["--data-dir", str(root), "--archive-json"]) == 0
    assert db_path.exists()
    assert any(root.glob("data.json.bak.*"))

"""verify_db_migration.py のスモークテスト。"""
from __future__ import annotations

import json

from scripts import verify_db_migration as verify
from scripts.migrate_json_to_db import main as migrate_main


def _minimal_project(tmp_path):
    data = tmp_path / "data"
    output = tmp_path / "output"
    data.mkdir()
    output.mkdir()
    (data / "watchlist.json").write_text(
        json.dumps([{"ticker": "7203.T", "status": "WATCHING"}]),
        encoding="utf-8",
    )
    (tmp_path / "portfolio_state.json").write_text(
        json.dumps({"cash_yen": 500_000}),
        encoding="utf-8",
    )
    (data / "last_report.json").write_text(
        json.dumps({"data_date": "2026-05-22"}),
        encoding="utf-8",
    )
    (output / "7203.T.json").write_text(
        json.dumps({"ticker": "7203.T"}),
        encoding="utf-8",
    )
    return tmp_path


def test_verify_passes_after_import(tmp_path):
    root = _minimal_project(tmp_path)
    db_url = f"sqlite:///{(root / 'data' / 'dpa.db').resolve()}"
    assert migrate_main(["--data-dir", str(root), "--database-url", db_url]) == 0
    assert verify.main(["--data-dir", str(root), "--database-url", db_url]) == 0


def test_verify_fails_on_mismatch(tmp_path):
    root = _minimal_project(tmp_path)
    db_url = f"sqlite:///{(root / 'data' / 'dpa.db').resolve()}"
    migrate_main(["--data-dir", str(root), "--database-url", db_url])
    (root / "data" / "watchlist.json").write_text("[]", encoding="utf-8")
    assert verify.main(["--data-dir", str(root), "--database-url", db_url]) == 1

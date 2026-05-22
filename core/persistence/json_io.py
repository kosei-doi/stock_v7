"""JSON ファイルの読み書き（Repository 用。web/api のロック付き I/O とは別）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise OSError(f"JSON の書き込みに失敗しました: {path}: {e}") from e

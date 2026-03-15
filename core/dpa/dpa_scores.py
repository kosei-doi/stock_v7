from __future__ import annotations

"""
DVC スコア履歴とトレンド（5日・20日）の計算モジュール。
"""

import json
from pathlib import Path
from typing import Dict

import numpy as np

from core.dvc.schema import DvcScoreOutput

SCORES_HISTORY_PATH = "data/scores_history.json"


def load_scores_history(path: str = SCORES_HISTORY_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_scores_history(history: dict, path: str = SCORES_HISTORY_PATH) -> None:
    p = Path(path)
    try:
        p.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise OSError(f"スコア履歴の書き込みに失敗しました: {path}: {e}") from e


def update_scores_history_for_date(
    date_key: str,
    dvc_results: Dict[str, DvcScoreOutput],
    path: str = SCORES_HISTORY_PATH,
) -> dict:
    """
    指定した日付キーに対して、ウォッチリスト銘柄のスコアを履歴に追記する。
    形式: { date: { ticker: { total, value, safety, momentum } } }
    """
    history = load_scores_history(path)
    day_entry = history.get(date_key, {})
    for ticker, out in dvc_results.items():
        s = out.scores
        day_entry[ticker] = {
            "total": s.total_score,
            "value": s.value_score,
            "safety": s.safety_score,
            "momentum": s.momentum_score,
        }
    history[date_key] = day_entry
    save_scores_history(history, path)
    return history


def _series_from_history(history: dict, ticker: str) -> list[float]:
    """scores_history から指定ティッカーの total スコア系列を日付順に抽出。"""
    items = []
    for date_key in sorted(history.keys()):
        day = history[date_key] or {}
        ent = day.get(ticker)
        if not ent:
            continue
        val = ent.get("total")
        if val is None:
            continue
        items.append(float(val))
    return items


def compute_score_trend(
    ticker: str,
    history: dict,
    short: int = 5,
    long: int = 20,
) -> dict:
    """
    指定ティッカーの total_score について、
    - last: 直近値（0〜100 を想定）
    - level: 直近値を 0〜1 に正規化
    - trend: 短期(5日)と中期(20日)の差分を [-1, +1] に正規化
    を返す。
    """
    vals = _series_from_history(history, ticker)
    if not vals:
        return {"last": None, "level": None, "trend": None}

    latest = float(vals[-1])
    level_norm = max(0.0, min(1.0, latest / 100.0))  # total_score は 0〜100 を想定

    arr = np.array(vals, dtype=float)
    n = arr.size
    if n < long + 1:
        # データが少ない場合はトレンドは None
        return {"last": latest, "level": level_norm, "trend": None}

    short_window = min(short, n)
    long_window = min(long, n)
    ma_short = arr[-short_window :].mean()
    ma_long = arr[-long_window :].mean()
    diff = float(ma_short - ma_long)

    # スコアは 0〜100 なので、差分 20 点程度で強いトレンドとみなして ±1 にクリップ
    scale = 20.0
    raw = diff / scale
    trend_norm = max(-1.0, min(1.0, raw))
    return {"last": latest, "level": level_norm, "trend": trend_norm}


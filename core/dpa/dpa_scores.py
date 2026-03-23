from __future__ import annotations

"""
DVC スコア履歴とトレンド計算モジュール。
trend は移動平均差分ではなく、直近履歴の線形回帰スロープを正規化して算出する。
"""

import json
import math
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from core.dvc.data_fetcher import fetch_price_history
from core.dvc.indicators import compute_volume_zscore, detect_macd_cross
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


def _combine_scores(values: list[Optional[float]], weights: list[float]) -> Optional[float]:
    if len(values) != len(weights):
        raise ValueError("values と weights の長さが一致しません")
    total_w = 0.0
    acc = 0.0
    for v, w in zip(values, weights):
        if v is None:
            continue
        acc += float(v) * float(w)
        total_w += float(w)
    if total_w == 0:
        return None
    return float(acc / total_w)


def _map_z_to_score(z: Optional[float], low_is_good: bool = True) -> Optional[float]:
    """Zスコアから 0〜100 点へ連続マッピング。"""
    if z is None:
        return None
    zf = float(z)
    score = 50.0 - 20.0 * zf if low_is_good else 50.0 + 20.0 * zf
    return float(max(0.0, min(100.0, score)))


def _score_momentum_from_price_df(price_df: pd.DataFrame) -> Optional[float]:
    """
    株価履歴だけで momentum_score を再計算する。
    DVC 本体の _score_momentum と同等の近似（MACD クロス鮮度 + 出来高 Z）を使う。
    """
    if price_df is None or price_df.empty:
        return None

    macd_cross_recent_days, _ = detect_macd_cross(price_df)
    volume_z = compute_volume_zscore(price_df)

    parts: list[Optional[float]] = []
    weights: list[float] = []
    if macd_cross_recent_days is not None:
        d = float(macd_cross_recent_days)
        freshness = math.exp(-max(0.0, d) / 10.0)  # DVC と同じ減衰係数
        parts.append(float(100.0 * freshness))
        weights.append(0.5)
    if volume_z is not None:
        parts.append(_map_z_to_score(volume_z, low_is_good=False))
        weights.append(0.5)
    return _combine_scores(parts, weights)


def _build_time_machine_series(
    ticker: str,
    latest_dvc: DvcScoreOutput,
    need_points: int,
    years: int,
) -> list[float]:
    """
    履歴不足を補うため、過去価格から疑似 total_score を逆算する。
    - Value/Safety は短期で不変とみなし最新値を固定
    - Momentum のみ「その時点までの価格」で再計算
    """
    if need_points <= 0:
        return []

    try:
        full_df = fetch_price_history(ticker, years)
    except Exception:
        return []
    if full_df is None or full_df.empty:
        return []

    value_fixed = latest_dvc.scores.value_score
    safety_fixed = latest_dvc.scores.safety_score
    pseudo: list[float] = []

    # 直近 need_points 営業日分を対象に、各日までの履歴で momentum を再計算。
    # n は DataFrame の有効行数（末尾日 index n-1）。
    n = len(full_df)
    span = min(need_points, n)
    start_idx = n - span
    for cut_idx in range(start_idx, n):
        # cut_idx 日時点までのデータ（含む）
        sub = full_df.iloc[: cut_idx + 1]
        mom = _score_momentum_from_price_df(sub)
        total = _combine_scores([value_fixed, safety_fixed, mom], [0.4, 0.4, 0.2])
        if total is not None:
            pseudo.append(float(total))

    return pseudo


def compute_score_trend(
    ticker: str,
    history: dict,
    latest_dvc: Optional[DvcScoreOutput] = None,
    years: int = 5,
    max_points: int = 10,
    slope_scale: float = 5.0,
) -> dict:
    """
    指定ティッカーの total_score について、
    - last: 直近値（0〜100 を想定）
    - level: 直近値を 0〜1 に正規化
    - trend: 直近履歴（最大 max_points 日）の線形回帰スロープを [-1, +1] に正規化
    を返す。
    """
    vals = _series_from_history(history, ticker)

    latest: Optional[float] = float(vals[-1]) if vals else None
    if latest is None and latest_dvc is not None and latest_dvc.scores.total_score is not None:
        latest = float(latest_dvc.scores.total_score)
        vals = [latest]
    if latest is None:
        return {"last": None, "level": None, "trend": None}

    # 履歴不足時は、価格履歴から疑似 total_score を逆算して系列を補う（タイムマシン）。
    if len(vals) < max_points and latest_dvc is not None:
        need = max_points - len(vals)
        pseudo = _build_time_machine_series(
            ticker=ticker,
            latest_dvc=latest_dvc,
            need_points=need,
            years=years,
        )
        # 実履歴と疑似履歴を合わせて直近系列を構築
        vals = (pseudo + vals)[-max_points:]

    level_norm = max(0.0, min(1.0, latest / 100.0))  # total_score は 0〜100 を想定

    recent_vals = vals[-max_points:] if max_points > 0 else vals
    arr = np.array(recent_vals, dtype=float)
    n = arr.size
    if n < 3:
        # 3点未満の回帰傾きは不安定なので、トレンドは中立（0.0）扱いにする。
        return {"last": latest, "level": level_norm, "trend": 0.0}

    # x: 0,1,2,... に対する y=score の一次回帰傾き（1日あたりのスコア変化量）。
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, arr, deg=1)[0])

    # 傾き 5pt/日 を「強いトレンド」とみなし、[-1, +1] に線形正規化してクリップ。
    scale = float(slope_scale) if slope_scale > 0 else 5.0
    trend_norm = max(-1.0, min(1.0, slope / scale))
    return {"last": latest, "level": level_norm, "trend": trend_norm}


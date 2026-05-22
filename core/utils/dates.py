"""
論理日付（JST 6 時区切り）の共通定義。
daily_routine の data_date と scores_history の日付キーで同一ルールを使う。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from core.utils.daily_cache import _now_jst

# 論理日付の区切り: 現在時刻からこの時間を引いた日付を「今日」とする（JST 0–5 時は前日扱い）
DEFAULT_LOGICAL_DATE_OFFSET_HOURS = 6


def logical_date_iso(
    now: Optional[datetime] = None,
    *,
    offset_hours: int = DEFAULT_LOGICAL_DATE_OFFSET_HOURS,
) -> str:
    """
    JST の論理日付を ISO 文字列（YYYY-MM-DD）で返す。

    例: 5/22 03:00 JST → 5/21（6 時間引いた日付）。
    now 省略時は _now_jst() を使用。
    """
    if now is None:
        now = _now_jst()
    return (now - timedelta(hours=offset_hours)).date().isoformat()

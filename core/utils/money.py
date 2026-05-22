"""円建て金額の正規化（整数円・切り捨て）。"""
from __future__ import annotations

import math
from typing import Union

Number = Union[int, float, str, None]


def yen_floor(value: Number) -> int:
    """
    円建て金額を整数円に切り捨てる。

    None や変換不能な値は 0。株価・比率・スコアには使わない。
    """
    if value is None:
        return 0
    try:
        return int(math.floor(float(value)))
    except (TypeError, ValueError):
        return 0

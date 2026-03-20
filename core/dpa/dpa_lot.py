"""
単元株（ロット）単位の切り捨て。

日本株の売買では「1 単元 = lot_size 株」（既定 100）を単位とする。
**ロット数に 1 未満の端数が出る場合は常に切り捨て**（0 ロット）とし、
金額÷単元代金も ``math.floor`` で整数ロット数に落とす（浮動小数誤差対策）。
"""
from __future__ import annotations

import math


def floor_lots_from_yen(value_yen: float, lot_cost_yen: float) -> int:
    """
    金額（円）から買える／売れるロット数。

    - ``value_yen`` が ``lot_cost_yen`` に満たない場合は 0。
    - ``value_yen / lot_cost_yen`` の小数部は切り捨て。
    """
    if value_yen <= 0 or lot_cost_yen <= 0:
        return 0
    return max(0, math.floor(float(value_yen) / float(lot_cost_yen)))


def shares_from_lots(n_lots: int, lot_size: int) -> int:
    """ロット数 × 単元株数。非正のロットは 0 株。"""
    if n_lots <= 0 or lot_size <= 0:
        return 0
    return int(n_lots) * int(lot_size)


def position_lots_and_shares(shares: int, lot_size: int) -> tuple[int, int]:
    """
    保有株数から (ロット数, 単元に乗る株数)。

    端株はロットに含めない（切り捨て）。例: 250 株・100 株単元 → (2, 200)。
    """
    if shares <= 0 or lot_size <= 0:
        return 0, 0
    ls = int(lot_size)
    n_lots = shares // ls
    return n_lots, n_lots * ls

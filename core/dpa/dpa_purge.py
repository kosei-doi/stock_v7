"""
DPA パージ（売却判定）: 目標構成比との乖離（オーバーウェイト）に基づき売却候補と見込み現金を算出する。
"""
from __future__ import annotations

import math

from core.dpa.dpa_lot import position_lots_and_shares, shares_from_lots
from core.dpa.dpa_schema import DpaPurgeOutput, MacroPhase, PurgeItem, SellReason


def run_purge(
    phase: MacroPhase,
    holdings: list[dict],
    target_weights: dict[str, float],
    current_prices: dict[str, float],
    total_capital_actual: float,
    lot_size: int = 100,
    purge_lot_threshold: float = 0.5,
) -> DpaPurgeOutput:
    """
    保有銘柄のみを対象とする。

    - 判定基準は「現在評価額が目標評価額をどれだけ超過しているか」のみ。
      許容乖離幅（%）は使わない。
    - 端数ロットの扱いは ``purge_lot_threshold``（既定 0.5）で非対称丸め:
      余りが閾値以上なら 1 ロット切り上げ、未満なら切り捨て。
    - マクロが PANIC のときは理由を ``MACRO_PANIC``、それ以外は ``SCORE_DECAY`` とする。

    売却指示リストには、単元株で実際に売却する株数が 1 株以上の銘柄だけを含める。
    """
    items: list[PurgeItem] = []
    estimated_cash_total = 0.0
    lot_round_up_threshold = max(0.0, min(1.0, float(purge_lot_threshold)))

    for h in holdings:
        ticker = h.get("ticker") or h.get("ticker_symbol")
        if not ticker:
            continue

        w_star = float(target_weights.get(ticker, 0.0))

        price = current_prices.get(ticker)
        shares = int(h.get("shares") or h.get("shares_held") or 0)

        if price is None or float(price) <= 0 or shares <= 0:
            continue

        current_value = float(shares) * float(price)
        target_value = float(total_capital_actual) * float(w_star)
        excess_value = current_value - target_value
        if excess_value <= 0:
            continue

        lot_cost = float(price) * float(lot_size)
        lots_held, _ = position_lots_and_shares(shares, lot_size)
        if lot_cost <= 0 or lots_held <= 0:
            lots_to_sell = 0
            sale_cash = 0.0
        else:
            # 100株の壁で売却見送りになり続けるのを防ぐため、端数ロットを閾値で切り上げる。
            # 1) 売りたいロット数（小数）
            excess_lots = excess_value / lot_cost
            # 2) 整数部（切り捨て）
            base_lots = math.floor(excess_lots)
            # 3) 端数
            remainder = excess_lots - float(base_lots)
            # 4) 閾値以上なら1ロット切り上げ
            if remainder >= lot_round_up_threshold:
                lots_to_sell = base_lots + 1
            else:
                lots_to_sell = base_lots
            # 5) 空売り防止
            lots_to_sell = min(lots_to_sell, lots_held)
            sale_cash = float(shares_from_lots(lots_to_sell, lot_size)) * float(price)

        shares_sell = shares_from_lots(lots_to_sell, lot_size)
        if shares_sell <= 0:
            continue

        estimated_cash_total += sale_cash

        if phase == MacroPhase.PANIC:
            reason = SellReason.MACRO_PANIC
            reason_ja = "現金比率を高めるためのオーバーウェイト解消（マクロ防衛）"
        else:
            reason = SellReason.SCORE_DECAY
            reason_ja = "ターゲット比率を上回るポジションの縮小（スコア低下・相対魅力度低下）"

        items.append(
            PurgeItem(
                ticker=ticker,
                reason=reason,
                reason_ja=reason_ja,
                current_price=float(price),
                stop_loss_price=None,
                score=None,
                shares_to_sell=shares_sell,
                estimated_sale_cash=sale_cash,
            )
        )

    return DpaPurgeOutput(
        phase=phase,
        items=items,
        total_count=len(items),
        estimated_cash_generated=float(estimated_cash_total),
    )

"""
DPA パージ（売却判定）: 目標構成比との乖離（オーバーウェイト）に基づき売却候補と見込み現金を算出する。
"""
from __future__ import annotations

from core.dpa.dpa_lot import floor_lots_from_yen, position_lots_and_shares, shares_from_lots
from core.dpa.dpa_schema import DpaPurgeOutput, MacroPhase, PurgeItem, SellReason


def run_purge(
    phase: MacroPhase,
    holdings: list[dict],
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    current_prices: dict[str, float],
    total_capital_actual: float,
    over_weight_threshold: float = 0.02,
    lot_size: int = 100,
) -> DpaPurgeOutput:
    """
    保有銘柄のみを対象とする。

    - ``over = max(0, w - w_i^*)`` が ``over_weight_threshold``（既定 2%pt）を超えた銘柄を
      売却候補とし、単元株（lot_size）単位で目標評価額まで縮小する見込みを計算する。
    - マクロが PANIC のときは理由を ``MACRO_PANIC``、それ以外は ``SCORE_DECAY`` とする。

    売却指示リストには、単元株で実際に売却する株数が 1 株以上の銘柄だけを含める。
    """
    items: list[PurgeItem] = []
    estimated_cash_total = 0.0

    for h in holdings:
        ticker = h.get("ticker") or h.get("ticker_symbol")
        if not ticker:
            continue

        w = float(current_weights.get(ticker, 0.0))
        w_star = float(target_weights.get(ticker, 0.0))
        over = max(0.0, w - w_star)
        if over <= over_weight_threshold:
            continue

        price = current_prices.get(ticker)
        shares = int(h.get("shares") or h.get("shares_held") or 0)

        if price is None or float(price) <= 0 or shares <= 0:
            continue

        position_value = float(shares) * float(price)
        target_value = float(total_capital_actual) * float(w_star)
        excess_value = max(0.0, position_value - target_value)

        lot_cost = float(price) * float(lot_size)
        lots_held, _ = position_lots_and_shares(shares, lot_size)
        if lot_cost <= 0 or lots_held <= 0:
            lots_to_sell = 0
            sale_cash = 0.0
        else:
            lots_from_excess = floor_lots_from_yen(excess_value, lot_cost)
            lots_to_sell = min(lots_from_excess, lots_held)
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

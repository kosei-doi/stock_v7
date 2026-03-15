"""
DPA パージ（売却判定）: マクロ悪化・損切り・スコア陳腐化に基づき売却推奨を出す。
"""
from __future__ import annotations

from typing import Optional

from core.dpa.dpa_schema import DpaPurgeOutput, MacroPhase, PurgeItem, SellReason


def run_purge(
    phase: MacroPhase,
    holdings: list[dict],
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    current_prices: dict[str, float],
    over_weight_threshold: float = 0.02,
) -> DpaPurgeOutput:
    """
    保有銘柄に対して「現在比率がターゲット比率をどれだけオーバーしているか」で売却候補を出す。

    - holdings: [{"ticker": "3197.T", ...}, ...]
    - current_weights: ticker -> 現在の構成比 w_i
    - target_weights: ticker -> ターゲット構成比 w_i^*
    - current_prices: ticker -> 現在価格（円）
    """
    items: list[PurgeItem] = []

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
        reason = SellReason.MACRO_PANIC if phase == MacroPhase.PANIC else SellReason.SCORE_DECAY
        reason_ja = (
            "現金比率を高めるためのオーバーウェイト解消（マクロ防衛）"
            if phase == MacroPhase.PANIC
            else "ターゲット比率を上回るポジションの縮小（スコア低下・相対魅力度低下）"
        )
        items.append(
            PurgeItem(
                ticker=ticker,
                reason=reason,
                reason_ja=reason_ja,
                current_price=price,
                stop_loss_price=None,
                score=None,
            )
        )

    return DpaPurgeOutput(phase=phase, items=items, total_count=len(items))

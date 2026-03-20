"""
DPA ドラフト（購入判定）: 仮想組入と動的N最適化により購入推奨を出す。
SYSTEM_OVERVIEW.md §5.2 に準拠。
"""
from __future__ import annotations

from typing import Dict

from core.dpa.dpa_lot import floor_lots_from_yen, shares_from_lots
from core.dpa.dpa_macro import MAX_POSITION_JPY as _DEFAULT_MAX_POSITION_JPY
from core.dpa.dpa_macro import MAX_POSITION_PCT as _DEFAULT_MAX_POSITION_PCT
from core.dpa.dpa_portfolio_score import compute_portfolio_total_score
from core.dpa.dpa_schema import BuyRecommendation, DpaDraftOutput, MacroPhase, MacroState
from core.dpa.dpa_weights import compute_target_weights
from core.dvc.schema import DvcScoreOutput


# 着火点: モメンタムスコアがこの値以上なら「陽転」とみなす
DEFAULT_IGNITION_MOMENTUM_THRESHOLD = 50.0
# 現物株の売買単位（日本株: 100株単位）
LOT_SIZE = 100
# 動的 N 最適化で仮想組入する最大候補数（設定未指定時の既定）
MAX_DRAFT_CANDIDATES = 5


def run_draft(
    available_budget: float,
    total_capital_actual: float,
    macro_state: MacroState,
    holdings: list[dict],
    watching_snapshots: list[DvcScoreOutput],
    current_prices: dict[str, float],
    target_weights: dict[str, float],
    current_weights: dict[str, float],
    score_trends: Dict[str, dict],
    portfolio_scores: Dict[str, float],
    all_scores: Dict[str, DvcScoreOutput],
    raw_available_budget: float | None = None,
    momentum_threshold: float = DEFAULT_IGNITION_MOMENTUM_THRESHOLD,
    lot_size: int = LOT_SIZE,
    max_position_pct: float | None = None,
    max_position_jpy: float | None = None,
    max_draft_candidates: int | None = None,
) -> DpaDraftOutput:
    """
    daily_routine から渡された予算上限で動的 N 最適化を実行する。

    Args:
        available_budget: シミュレーションに使う予算（PANIC 時は 0）。
        total_capital_actual: 総資産（現金＋株式評価額）。
        raw_available_budget: レポート用。未指定時は available_budget を使用。
        その他: SYSTEM_OVERVIEW §5.2 参照。

    Returns:
        DpaDraftOutput:
            - raw_available_budget: 売却見込み反映後の理論枠（呼び出し側で設定推奨）
            - draft_budget_cap: 実際にシミュレーションに渡した予算上限
            - available_budget: 採用シナリオの消費額 total_spent
    """
    raw_for_report = float(raw_available_budget) if raw_available_budget is not None else float(available_budget)
    # ベースPFの構成比・ターゲット重みは参照のみ（シミュレーションでは仮想PFで再計算）
    _ = (target_weights, current_weights)

    pos_pct = float(max_position_pct) if max_position_pct is not None else float(_DEFAULT_MAX_POSITION_PCT)
    pos_jpy = float(max_position_jpy) if max_position_jpy is not None else float(_DEFAULT_MAX_POSITION_JPY)
    cap_n = int(max_draft_candidates) if max_draft_candidates is not None else int(MAX_DRAFT_CANDIDATES)
    if cap_n < 1:
        cap_n = 1

    # パニックモード、またはシミュレーション予算が非正なら買いなし
    if macro_state.phase == MacroPhase.PANIC or available_budget <= 0:
        return DpaDraftOutput(
            phase=macro_state.phase,
            draft_budget_cap=0.0,
            raw_available_budget=raw_for_report,
            available_budget=0.0,
            recommendations=[],
        )

    sim_budget = float(available_budget)

    holding_tickers = {
        h.get("ticker") or h.get("ticker_symbol")
        for h in holdings
        if h.get("ticker") or h.get("ticker_symbol")
    }

    candidates: list[tuple[DvcScoreOutput, float]] = []
    for d in watching_snapshots:
        if d.ticker in holding_tickers:
            continue
        mom = d.scores.momentum_score
        if mom is None or mom < momentum_threshold:
            continue
        pscore = (
            float(portfolio_scores[d.ticker])
            if d.ticker in portfolio_scores
            else compute_portfolio_total_score(d, macro_state)
        )
        candidates.append((d, pscore))

    candidates.sort(key=lambda x: x[1], reverse=True)

    if not candidates:
        return DpaDraftOutput(
            phase=macro_state.phase,
            draft_budget_cap=sim_budget,
            raw_available_budget=raw_for_report,
            available_budget=0.0,
            recommendations=[],
        )

    max_n = min(cap_n, len(candidates))
    best_score = 0.0
    best_buys: list[BuyRecommendation] = []

    holdings_tickers_list = sorted(holding_tickers)

    for n in range(1, max_n + 1):
        slice_candidates = candidates[:n]
        current_candidates = [d for d, _ in slice_candidates]
        candidate_tickers = [d.ticker for d in current_candidates]

        virtual_tickers = set(candidate_tickers) | set(holdings_tickers_list)

        dvc_subset: Dict[str, DvcScoreOutput] = {}
        score_trends_subset: Dict[str, dict] = {}
        portfolio_scores_subset: Dict[str, float] = {}
        for t in virtual_tickers:
            if t not in all_scores:
                continue
            dvc_subset[t] = all_scores[t]
            if t in score_trends:
                score_trends_subset[t] = score_trends[t]
            if t in portfolio_scores:
                portfolio_scores_subset[t] = portfolio_scores[t]

        if not dvc_subset:
            continue

        simulated_weights = compute_target_weights(
            dvc_results=dvc_subset,
            score_trends=score_trends_subset,
            macro_state=macro_state,
            portfolio_scores=portfolio_scores_subset or None,
        )

        scenario_budget = sim_budget
        scenario_buys: list[BuyRecommendation] = []

        for d in current_candidates:
            ticker = d.ticker
            price = current_prices.get(ticker)
            if price is None or price <= 0:
                continue

            w = float(simulated_weights.get(ticker, 0.0))
            if w <= 0:
                continue

            # target_jpy = total_capital_actual * simulated_weights[ticker]（§5.2）
            target_jpy = float(total_capital_actual) * w
            max_pos_value = min(pos_pct * float(total_capital_actual), pos_jpy)
            target_jpy = min(target_jpy, max_pos_value)
            if target_jpy <= 0:
                continue

            lot_cost = float(price) * float(lot_size)
            if lot_cost <= 0:
                continue

            # 単元株ロット計算: 1 ロットに満たない金額は切り捨て（floor_lots_from_yen）
            max_lots_by_target = floor_lots_from_yen(target_jpy, lot_cost)
            max_lots_by_budget = floor_lots_from_yen(scenario_budget, lot_cost)
            lots = min(max_lots_by_target, max_lots_by_budget)
            if lots <= 0:
                continue

            shares = shares_from_lots(lots, lot_size)
            cost = float(shares) * float(price)
            if cost <= 0 or cost > scenario_budget:
                continue

            scenario_budget -= cost
            score_value = portfolio_scores.get(ticker, compute_portfolio_total_score(d, macro_state))
            scenario_buys.append(
                BuyRecommendation(
                    ticker=ticker,
                    name=d.name,
                    shares=shares,
                    limit_price=None,
                    score=score_value,
                    budget_used=cost,
                )
            )

        if not scenario_buys:
            scenario_score = 0.0
        else:
            total_spent = sim_budget - scenario_budget
            if total_spent <= 0 or sim_budget <= 0:
                scenario_score = 0.0
            else:
                utilization = total_spent / sim_budget
                count = len(scenario_buys)
                weighted_score_numer = sum((b.score or 0.0) * b.budget_used for b in scenario_buys)
                weighted_score = weighted_score_numer / total_spent
                # scenario_score = weighted_score * (1 + 0.1 * count) * utilization
                scenario_score = weighted_score * (1.0 + 0.1 * float(count)) * utilization

        if scenario_score > best_score:
            best_score = scenario_score
            best_buys = list(scenario_buys)

    total_spent_out = sum(b.budget_used for b in best_buys) if best_buys else 0.0

    return DpaDraftOutput(
        phase=macro_state.phase,
        draft_budget_cap=sim_budget,
        raw_available_budget=raw_for_report,
        available_budget=float(total_spent_out),
        recommendations=sorted(best_buys, key=lambda b: (b.score or 0.0), reverse=True),
    )

"""
DPA ドラフト（購入判定）: 目標現金比率から空き予算を算出し、
着火点を迎えた高スコア銘柄に ATR サイジングで株数を決めて購入推奨を出す。
"""
from __future__ import annotations

from typing import Dict, Optional

from core.dpa.dpa_macro import MAX_POSITION_JPY, MAX_POSITION_PCT
from core.dpa.dpa_portfolio_score import compute_portfolio_total_score
from core.dpa.dpa_schema import DpaDraftOutput, MacroPhase, MacroState, BuyRecommendation
from core.dvc.schema import DvcScoreOutput


# 着火点: モメンタムスコアがこの値以上なら「陽転」とみなす
DEFAULT_IGNITION_MOMENTUM_THRESHOLD = 50.0
# 現物株の売買単位（日本株: 100株単位）
LOT_SIZE = 100
# 動的 N 最適化で仮想組入する最大候補数
MAX_DRAFT_CANDIDATES = 5


def _available_budget(
    cash_current: float,
    total_capital: float,
    target_cash_ratio: float,
) -> float:
    """本日の新規買付パワー（空き予算）。現在現金 - 目標現金。"""
    target_cash = total_capital * target_cash_ratio
    return max(0.0, cash_current - target_cash)


def run_draft(
    macro_state: MacroState,
    total_capital: float,
    cash_current: float,
    holdings_value: float,
    holdings: list[dict],
    watching_snapshots: list[DvcScoreOutput],
    current_prices: dict[str, float],
    target_weights: dict[str, float],
    current_weights: dict[str, float],
    score_trends: Dict[str, dict],
    portfolio_scores: Dict[str, float],
    all_scores: Dict[str, DvcScoreOutput],
    momentum_threshold: float = DEFAULT_IGNITION_MOMENTUM_THRESHOLD,
    lot_size: int = LOT_SIZE,
) -> DpaDraftOutput:
    """
    監視銘柄（WATCHING）のうちスコア・トレンドが良く、かつターゲット構成比に対して
    軽すぎる銘柄をスコア優先でピックアップし、今日使ってよい予算の範囲で
    100株単位・1銘柄15%/MAX_POSITION_JPY 上限を守りながら新規購入推奨を出す。
    パニックモードでは新規買い停止とするが、その場合でも「理論上の空き予算」は
    raw_available_budget に保持する。
    """
    total_capital_actual = cash_current + holdings_value
    raw_budget = _available_budget(
        cash_current=cash_current,
        total_capital=total_capital_actual,
        target_cash_ratio=macro_state.target_cash_ratio,
    )

    # パニックモード、または理論上の空き予算が非正なら実際の新規買付は 0 とする
    if macro_state.phase == MacroPhase.PANIC or raw_budget <= 0:
        return DpaDraftOutput(
            phase=macro_state.phase,
            available_budget=0.0,
            raw_available_budget=float(raw_budget),
            recommendations=[],
        )

    # 本日の新規買付パワー（シミュレーションに使う上限）
    available_budget = float(raw_budget)

    # WATCHING かつ未保有、モメンタム着火点を超える銘柄のみを候補にする
    holding_tickers = {
        h.get("ticker") or h.get("ticker_symbol")
        for h in holdings
        if h.get("ticker") or h.get("ticker_symbol")
    }

    # 候補: (DvcScoreOutput, portfolio_score)
    candidates: list[tuple[DvcScoreOutput, float]] = []
    for d in watching_snapshots:
        if d.ticker in holding_tickers:
            continue
        mom = d.scores.momentum_score
        if mom is None or mom < momentum_threshold:
            continue
        # ポートフォリオスコアがあればそれを優先、なければ compute_portfolio_total_score で代用
        pscore = float(portfolio_scores.get(d.ticker)) if d.ticker in portfolio_scores else compute_portfolio_total_score(d, macro_state)
        candidates.append((d, pscore))

    # ポートフォリオスコア降順でソート
    candidates.sort(key=lambda x: x[1], reverse=True)

    if not candidates or available_budget <= 0:
        return DpaDraftOutput(
            phase=macro_state.phase,
            available_budget=0.0,
            raw_available_budget=float(raw_budget),
            recommendations=[],
        )

    # 動的 N 最適化: N = 1..max_n で仮想組入シミュレーション
    max_n = min(MAX_DRAFT_CANDIDATES, len(candidates))
    best_score = 0.0
    best_buys: list[BuyRecommendation] = []
    best_remaining_budget = available_budget

    from core.dpa.dpa_weights import compute_target_weights

    # 既存保有銘柄（holdings）に対応するスコアオブジェクト
    holdings_tickers_list = sorted(
        {
            h.get("ticker") or h.get("ticker_symbol")
            for h in holdings
            if h.get("ticker") or h.get("ticker_symbol")
        }
    )

    for n in range(1, max_n + 1):
        # a. 候補上位 N 銘柄を仮想ポートフォリオに含める
        slice_candidates = candidates[:n]
        current_candidates = [d for d, _ in slice_candidates]
        candidate_tickers = [d.ticker for d in current_candidates]

        # 仮想ポートフォリオに含める全ティッカー（既存保有 + 新規候補）
        virtual_tickers = set(candidate_tickers) | set(holdings_tickers_list)

        # compute_target_weights 用の入力を「仮想ポートフォリオ」に限定
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

        # b. 仮想ターゲット構成比を算出
        simulated_weights = compute_target_weights(
            dvc_results=dvc_subset,
            score_trends=score_trends_subset,
            macro_state=macro_state,
            portfolio_scores=portfolio_scores_subset or None,
        )

        # c. シナリオごとの残予算と買付リスト
        scenario_budget = available_budget
        scenario_buys: list[BuyRecommendation] = []

        # d. current_candidates をループし、目標購入金額を計算
        for d in current_candidates:
            ticker = d.ticker
            price = current_prices.get(ticker)
            if price is None or price <= 0:
                continue

            w = float(simulated_weights.get(ticker, 0.0))
            if w <= 0:
                continue

            target_jpy = total_capital_actual * w
            # e. 1 銘柄上限（15% or MAX_POSITION_JPY）の小さい方でクリップ
            max_pos_value = min(MAX_POSITION_PCT * total_capital_actual, MAX_POSITION_JPY)
            target_jpy = min(target_jpy, max_pos_value)
            if target_jpy <= 0:
                continue

            lot_cost = price * lot_size
            if lot_cost <= 0:
                continue

            # f. 1単元単位で target_jpy と予算の両方を満たす最大株数を計算
            max_lots_by_target = int(target_jpy // lot_cost)
            max_lots_by_budget = int(scenario_budget // lot_cost)
            lots = min(max_lots_by_target, max_lots_by_budget)
            if lots <= 0:
                continue

            shares = lots * lot_size
            cost = shares * price
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

        # 何も買えなかったシナリオは score=0 とする
        if not scenario_buys:
            scenario_score = 0.0
        else:
            total_spent = available_budget - scenario_budget
            if total_spent <= 0 or available_budget <= 0:
                scenario_score = 0.0
            else:
                utilization = total_spent / available_budget
                count = len(scenario_buys)
                weighted_score_numer = sum((b.score or 0.0) * b.budget_used for b in scenario_buys)
                weighted_score = weighted_score_numer / total_spent if total_spent > 0 else 0.0
                # 分散ボーナス係数 0.1
                scenario_score = weighted_score * (1.0 + 0.1 * count) * utilization

        if scenario_score > best_score:
            best_score = scenario_score
            best_buys = scenario_buys
            best_remaining_budget = scenario_budget

    return DpaDraftOutput(
        phase=macro_state.phase,
        # 実際に使う予算額（最適シナリオでの支出）
        available_budget=available_budget - best_remaining_budget if best_buys else 0.0,
        raw_available_budget=float(raw_budget),
        # 最適シナリオでの買付リストをスコア降順で返す
        recommendations=sorted(best_buys, key=lambda b: (b.score or 0.0), reverse=True),
    )

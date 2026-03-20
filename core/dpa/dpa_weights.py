from __future__ import annotations

"""
ターゲット構成比（w_i^*）を計算するモジュール。
レベル（現在の total_score）とトレンド（5日・20日差分）、
およびマクロの target_cash_ratio から非現金部分を銘柄ごとに割り振る。
"""

from typing import AbstractSet, Dict, Optional

from core.dpa.dpa_schema import MacroState
from core.dvc.schema import DvcScoreOutput


def compute_target_weights(
    dvc_results: Dict[str, DvcScoreOutput],
    score_trends: Dict[str, dict],
    macro_state: MacroState,
    alpha_level: float = 0.7,
    beta_trend: float = 0.3,
    portfolio_scores: Optional[Dict[str, float]] = None,
    allocation_tickers: Optional[AbstractSet[str]] = None,
) -> Dict[str, float]:
    """
    非現金部分 (1 - target_cash_ratio) を、
    raw_i = max(0, alpha * level_i + beta * trend_i) に
    β, R², α, ATR からの連続的なリスク調整を掛けたうえで正規化して割り振る。

    - **allocation_tickers** を指定した場合、その集合に含まれ **かつ** ``dvc_results`` にある銘柄
      だけを正規化の母集団とし、それらの ``target_weights`` の合計が ``non_cash`` になる
      （日次レポートの「保有のみで目標比率を山分け」用）。
      未指定時は従来どおり ``dvc_results`` の全銘柄が対象。
    - portfolio_scores を渡す場合、level には「ポートフォリオ用 total_score」の 0〜1 正規化を使う（購入順と整合）。
    - マクロが防御的（target_cash_ratio が高い）ほど、高β・高R² 銘柄の raw を抑える。
    - ATR が大きい銘柄は常に raw を少し抑え、α がプラスの銘柄はわずかに押し上げる。

    score_trends[ticker] は {"level": float|None, "trend": float|None} を想定。
    """
    non_cash = max(0.0, min(1.0, 1.0 - macro_state.target_cash_ratio))
    raw: Dict[str, float] = {}

    if allocation_tickers is not None:
        eligible: list[str] = [t for t in allocation_tickers if t in dvc_results]
    else:
        eligible = list(dvc_results.keys())

    # マクロ防御の強さ（0〜1）
    defense_intensity = min(max(macro_state.target_cash_ratio - 0.4, 0.0) / 0.4, 1.0)

    for ticker in eligible:
        out = dvc_results[ticker]
        st = score_trends.get(ticker) or {}
        trend = st.get("trend")
        # レベル: ポートフォリオ用スコアがあればそれで統一（購入順と整合）、なければ履歴の level
        if portfolio_scores and ticker in portfolio_scores:
            l = max(0.0, min(1.0, portfolio_scores[ticker] / 100.0))
        else:
            level = st.get("level")
            if level is None and trend is None:
                continue
            l = float(level) if level is not None else 0.0
        t = float(trend) if trend is not None else 0.0
        if l == 0.0 and t == 0.0:
            continue

        # ベース: スコアレベルとトレンド
        base_raw = alpha_level * l + beta_trend * t
        if base_raw <= 0:
            continue

        # リスク・相関情報
        ml = getattr(out, "market_linkage", None)
        rm = getattr(out, "risk_metrics", None)
        beta = getattr(ml, "beta", None) if ml is not None else None
        r2 = getattr(ml, "r_squared", None) if ml is not None else None
        alpha = getattr(ml, "alpha", None) if ml is not None else None
        atr_pct = getattr(rm, "atr_percent", None) if rm is not None else None

        # βとR²：防御モードでは高β・高R² を抑える
        beta_penalty = 1.0
        if beta is not None and defense_intensity > 0:
            # β > 1 の分だけ、max 20% までゆるやかに減衰
            over = max(0.0, float(beta) - 1.0)
            beta_penalty -= min(0.2, over * 0.1 * defense_intensity)

        r2_penalty = 1.0
        if r2 is not None and defense_intensity > 0:
            # 高い R² ほど（指数とべったりほど）少しだけ抑える（最大 20%）
            r2_penalty -= min(0.2, float(r2) * 0.2 * defense_intensity)

        # ATR%: 高ボラ銘柄は常に少し抑える（最大 30%）
        atr_penalty = 1.0
        if atr_pct is not None:
            atr = max(0.0, float(atr_pct))
            atr_penalty -= min(0.3, atr * 0.02)  # ATR 15% で ~0.3 減衰

        # α: プラスα銘柄はわずかに底上げ（最大 +10%）
        alpha_boost = 1.0
        if alpha is not None:
            # α は日次の超過リターン想定なので小さくスケール
            a = float(alpha)
            if a > 0:
                alpha_boost += min(0.1, a * 100.0)

        risk_factor = beta_penalty * r2_penalty * atr_penalty * alpha_boost
        # 極端になりすぎないようにクリップ
        risk_factor = max(0.5, min(1.5, risk_factor))

        r = base_raw * risk_factor
        if r <= 0:
            continue
        raw[ticker] = r

    total_raw = sum(raw.values())
    if total_raw <= 0:
        return {t: 0.0 for t in dvc_results.keys()}

    weights: Dict[str, float] = {}
    for ticker, r in raw.items():
        w = non_cash * (r / total_raw)
        weights[ticker] = float(w)
    if allocation_tickers is not None:
        for t in dvc_results:
            if t not in weights:
                weights[t] = 0.0
    return weights


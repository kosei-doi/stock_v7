"""
ポートフォリオ用 total_score の算出。
DVC の total_score に β, R², α, ATR% の4指標を加味し、
市場状況（マクロの防御度）に応じて各指標の影響度を変えた「新しい total_score」を計算する。
購入順やターゲット構成比のベースとして利用する。
"""
from __future__ import annotations

from core.dpa.dpa_schema import MacroState
from core.dvc.schema import DvcScoreOutput


def get_defense_intensity(macro_state: MacroState) -> float:
    """
    マクロの防御度を 0〜1 で返す。
    target_cash_ratio が高いほど 1 に近づく（警戒・パニック寄り）。
    """
    r = macro_state.target_cash_ratio
    # 0.4 以下なら 0、0.8 以上なら 1、その間は線形
    return min(1.0, max(0.0, (r - 0.4) / 0.4))


def compute_portfolio_total_score(
    d: DvcScoreOutput,
    macro_state: MacroState,
) -> float:
    """
    ポートフォリオ観点で再計算した total_score を返す。
    - ベースは DVC の total_score（0〜100 想定）。
    - β, R², α, ATR% の4指標で加減し、市場状況（防御度）に応じて各指標の影響度を変える。
    - 防御が強いとき: 高β・高R²を強く減点、高ATRも減点。αは控えめに加点。
    - 防御が弱いとき: β・R²の減点は弱く、αをやや強く加点。ATRは常にやや減点。
    """
    base = float(d.scores.total_score or 0.0)
    defense = get_defense_intensity(macro_state)

    ml = getattr(d, "market_linkage", None)
    rm = getattr(d, "risk_metrics", None)
    _b = getattr(ml, "beta", None) if ml is not None else None
    _r = getattr(ml, "r_squared", None) if ml is not None else None
    _a = getattr(ml, "alpha", None) if ml is not None else None
    _atr = getattr(rm, "atr_percent", None) if rm is not None else None
    beta = float(_b) if _b is not None else None
    r2 = float(_r) if _r is not None else None
    alpha = float(_a) if _a is not None else None
    atr_pct = float(_atr) if _atr is not None else None

    # 各指標の影響度（市場状況で変化）
    # 防御時は β, R², ATR のペナルティを強く、α のボーナスは控えめに
    w_beta_penalty = 5.0 + 15.0 * defense   # 高βの減点係数
    w_r2_penalty = 5.0 + 10.0 * defense    # 高R²の減点係数
    w_alpha_bonus = 50.0 + 50.0 * (1.0 - defense)  # α加点（リスクオンで大きく）
    w_atr_penalty = 0.3 + 0.4 * defense    # ATR%の減点係数

    adj = 0.0
    if beta is not None and beta > 1.0:
        adj -= w_beta_penalty * (beta - 1.0)
    if r2 is not None and r2 > 0:
        adj -= w_r2_penalty * r2
    if alpha is not None and alpha > 0:
        # α は日次リターン程度の小さな値なので 10000 倍して bps 扱いでスコア化
        adj += w_alpha_bonus * alpha * 10000.0 / 100.0  # 数 bps で 1〜数 pt
    if atr_pct is not None and atr_pct > 0:
        adj -= w_atr_penalty * atr_pct

    score = base + adj
    # 順序が崩れないよう極端な値だけクリップ（0〜100 外も許容してソートに使う）
    return max(0.0, min(150.0, score))

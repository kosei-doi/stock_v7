"""
DPA マクロ環境モジュール:
- TOPIX の MACD からトレンド指標（-1〜+1）を計算
- VI の履歴からZスコアを計算
- それらの連続値から 1 本の式で目標現金比率を決定し、
  フェーズ名（巡航/警戒/…）は後付けラベルとして付与する。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from core.dpa.dpa_schema import MacroPhase, MacroState
from core.dvc.indicators import compute_macd

# 1銘柄あたりの最大投資割合と絶対上限（資金防衛ルール用）
MAX_POSITION_PCT = 0.15
MAX_POSITION_JPY = 750_000

def compute_vi_z(vi_series: Optional[pd.Series], window: int = 60) -> Optional[float]:
    """VI のZスコア（直近値が過去 window 日の分布のどこにいるか）を返す。"""
    if vi_series is None or vi_series.empty:
        return None
    s = vi_series.dropna()
    if s.empty:
        return None
    if len(s) < window + 1:
        window = len(s) - 1
    if window <= 1:
        return None
    recent = float(s.iloc[-1])
    hist = s.iloc[-window - 1 : -1]
    arr = hist.to_numpy(dtype=float)
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=0))
    if sigma == 0.0 or np.isnan(sigma):
        return None
    return float((recent - mu) / sigma)


def compute_macd_trend(
    bench_df: pd.DataFrame,
    ma_window: int = 5,
    z_window: int = 60,
) -> Optional[float]:
    """
    ベンチマークの MACD スプレッドを、ローリング Z スコア化して -1.0〜+1.0 の連続値に落とす。

    意図:
    - 「直近5日 vs その前5日」の差分だけだとゲインが大きくバンバン制御になりやすい。
    - スプレッドを平滑化し、過去60営業日の分布の中で「今どれだけ外れているか」
      を Z で見たうえで [-3,3] にクリップし、/3 で線形に [-1,1] へ写すことで
      後続の現金比率式（b_macd による重み）の偏りを抑える。

    手順:
    1) spread = macd - signal（MACD ヒストグラム相当）
    2) spread_5d = spread の ma_window 日移動平均（ノイズ低減）
    3) spread_5d のローリング z_window 日の平均・標準偏差で Z = (spread_5d - mean) / (std + eps)
    4) 直近の Z を [-3, +3] にクリップ
    5) macd_trend = clipped_z / 3.0  → 理論上 [-1, 1]（端は ±1 に張り付かないことも多い）

    データ不足時（ローリングがまだ埋まらない等）は None。
    """
    _EPS = 1e-8
    # 5日MA + 60日ローリングで最後の行が有効になる目安（index 0 始まりで spread_5d が 4 から有効なら 63 番目まで必要）
    min_len = ma_window + z_window - 1
    if bench_df is None or bench_df.empty or len(bench_df) < min_len:
        return None

    macd, signal = compute_macd(bench_df)
    spread = macd - signal
    if isinstance(spread, pd.DataFrame):
        spread = spread.iloc[:, 0]
    spread = spread.dropna()
    if len(spread) < min_len:
        return None

    # 2) スプレッドの移動平均（日々のノイズ抑制）
    spread_ma = spread.rolling(window=ma_window, min_periods=ma_window).mean()

    # 3) ローリング平均・標準偏差による Z（同じ z_window 内の分布に対する外れ度）
    roll = spread_ma.rolling(window=z_window, min_periods=z_window)
    roll_mean = roll.mean()
    roll_std = roll.std(ddof=0)
    z_score = (spread_ma - roll_mean) / (roll_std + _EPS)

    z_last = z_score.iloc[-1]
    if pd.isna(z_last) or not np.isfinite(z_last):
        return None

    # 4) 外れ値の抑制  5) -1〜1 への線形正規化（±3σ を ±1 に対応づける）
    z_clipped = float(np.clip(z_last, -3.0, 3.0))
    return z_clipped / 3.0


def _continuous_cash_ratio(
    vi_z: Optional[float],
    macd_trend: Optional[float],
    mu_cash: float = 0.4,
    a_vi: float = 0.1,
    b_macd: float = 0.1,
    min_ratio: float = 0.2,
    max_ratio: float = 0.8,
) -> float:
    """VI ZスコアとMACDトレンドから連続的に現金比率を計算する。"""
    z = vi_z if vi_z is not None else 0.0
    t = macd_trend if macd_trend is not None else 0.0
    # 恐怖が高いほど現金比率↑、トレンド上向きほど現金比率↓
    cash = mu_cash + a_vi * max(z, 0.0) - b_macd * t
    if cash < min_ratio:
        cash = min_ratio
    if cash > max_ratio:
        cash = max_ratio
    return float(cash)


def _phase_from_cash(cash_ratio: float) -> MacroPhase:
    """現金比率からフェーズラベルを後付けで決める。"""
    if cash_ratio <= 0.3:
        return MacroPhase.CRUISE
    if cash_ratio <= 0.5:
        return MacroPhase.CAUTION
    if cash_ratio >= 0.7:
        return MacroPhase.PANIC
    return MacroPhase.REVERSAL


def get_macro_state(
    bench_df: pd.DataFrame,
    vi_series: Optional[pd.Series] = None,
    mu_cash: float = 0.4,
    a_vi: float = 0.1,
    b_macd: float = 0.1,
    macd_scale: float = 0.002,
    min_cash_ratio: float = 0.2,
    max_cash_ratio: float = 0.8,
) -> MacroState:
    """
    TOPIX の MACD トレンドと VI シリーズから連続的に現金比率を計算し、
    フェーズ名は現金比率から後付けで決める。

    macd_scale は後方互換のため受け取るが、macd_trend は Z スコア方式のため未使用。
    """
    vi_z = compute_vi_z(vi_series)
    # macd_scale: 呼び出し元・config 互換のため引数に残す（macd_trend は Z スコア方式で未使用）
    macd_trend = compute_macd_trend(bench_df)
    cash_ratio = _continuous_cash_ratio(
        vi_z=vi_z,
        macd_trend=macd_trend,
        mu_cash=mu_cash,
        a_vi=a_vi,
        b_macd=b_macd,
        min_ratio=min_cash_ratio,
        max_ratio=max_cash_ratio,
    )
    phase = _phase_from_cash(cash_ratio)
    phase_name_ja = {
        MacroPhase.CRUISE: "巡航モード【オフェンス】",
        MacroPhase.CAUTION: "警戒モード【ロー・ベータ・シフト】",
        MacroPhase.PANIC: "パニック防衛モード【キャッシュ・イズ・キング】",
        MacroPhase.REVERSAL: "反転狙撃モード【バリュー・スナイプ】",
    }[phase]
    return MacroState(
        phase=phase,
        phase_name_ja=phase_name_ja,
        target_cash_ratio=cash_ratio,
        vi_z=vi_z,
        macd_trend=macd_trend,
    )

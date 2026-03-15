"""
DPA（Dynamic Portfolio Architect）の入出力スキーマ。
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MacroPhase(str, Enum):
    """マクロ環境の4フェーズ。"""
    CRUISE = "cruise"           # 巡航モード【オフェンス】
    CAUTION = "caution"          # 警戒モード【ロー・ベータ・シフト】
    PANIC = "panic"              # パニック防衛モード【キャッシュ・イズ・キング】
    REVERSAL = "reversal"        # 反転狙撃モード【バリュー・スナイプ】


class MacroState(BaseModel):
    """マクロ判定結果（連続量ベース）。"""
    phase: MacroPhase
    phase_name_ja: str = Field(..., description="フェーズ名（日本語）")
    target_cash_ratio: float = Field(..., description="目標現金比率 0〜1")
    vi_z: Optional[float] = Field(None, description="VIのZスコア")
    macd_trend: Optional[float] = Field(None, description="MACDトレンド指標（-1〜+1）")


class SellReason(str, Enum):
    """売却理由。"""
    MACRO_PANIC = "macro_panic"       # マクロ悪化（防衛モード移行）
    STOP_LOSS = "stop_loss"           # ATR損切りライン抵触
    SCORE_DECAY = "score_decay"       # スコア陳腐化


class PurgeItem(BaseModel):
    """パージ（売却）1件。"""
    ticker: str
    reason: SellReason
    reason_ja: str = Field(..., description="理由の日本語説明")
    current_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    score: Optional[float] = None


class DpaPurgeOutput(BaseModel):
    """パージ（売却判定）の出力。"""
    phase: MacroPhase
    items: list[PurgeItem] = Field(default_factory=list)
    total_count: int = 0


class BuyRecommendation(BaseModel):
    """購入推奨1件。"""
    ticker: str
    name: Optional[str] = None
    shares: int = Field(..., description="推奨株数")
    limit_price: Optional[float] = Field(None, description="逆指値（円）")
    score: Optional[float] = None
    budget_used: float = Field(0.0, description="使用予算（円）")


class DpaDraftOutput(BaseModel):
    """ドラフト（購入判定）の出力。"""
    phase: MacroPhase
    available_budget: float = Field(0.0, description="本日の新規買付パワー（実際に使う額、円）")
    raw_available_budget: Optional[float] = Field(
        None, description="マクロ防衛設定を無視した理論上の新規買付パワー（円）"
    )
    recommendations: list[BuyRecommendation] = Field(default_factory=list)


class DpaDailyReport(BaseModel):
    """日次レポート（DPA 全体の出力）。"""
    created_at: str = Field(..., description="画面表示用の実際の生成日時（例: 2026-03-12 05:30:00 JST）")
    data_date: str = Field(..., description="論理計算用の基準日（例: 2026-03-11）")
    target_cash_ratio: float = Field(..., description="本日の目標現金比率 0〜1")
    phase: MacroPhase
    phase_name_ja: str = ""
    vi_z: Optional[float] = Field(None, description="VIのZスコア（参考情報）")
    macd_trend: Optional[float] = Field(None, description="MACDトレンド指標（参考情報）")
    cash_yen: Optional[float] = Field(None, description="現金残高（円）")
    total_capital_yen: Optional[float] = Field(None, description="総資産（円）")
    equity_value_yen: Optional[float] = Field(None, description="株式評価額（円）")
    ticker_names: Optional[dict[str, str]] = Field(
        default=None, description="銘柄コード -> 会社名"
    )
    last_prices: Optional[dict[str, float]] = Field(
        default=None, description="銘柄コード -> 直近株価（終値）"
    )
    current_weights: Optional[dict[str, float]] = Field(
        default=None, description="銘柄ごとの現在構成比"
    )
    target_weights: Optional[dict[str, float]] = Field(
        default=None, description="銘柄ごとのターゲット構成比"
    )
    score_trends: Optional[dict[str, dict]] = Field(
        default=None, description="銘柄ごとのスコアレベル・トレンド"
    )
    portfolio_scores: Optional[dict[str, float]] = Field(
        default=None, description="銘柄ごとのポートフォリオ用 total_score（表示順・購入順に使用）"
    )
    purge: DpaPurgeOutput = Field(default_factory=DpaPurgeOutput)
    draft: DpaDraftOutput = Field(default_factory=DpaDraftOutput)
    report_text: Optional[str] = Field(None, description="プレーンテキストレポート")

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class PriceHistoryOverview(BaseModel):
    """取得した株価データの概要。"""
    rows: int = Field(..., description="行数（日数）")
    date_min: Optional[str] = Field(None, description="先頭日付")
    date_max: Optional[str] = Field(None, description="最終日付")
    columns: list[str] = Field(default_factory=list, description="カラム名一覧")
    last_close: Optional[float] = Field(None, description="直近終値")
    empty: bool = Field(False, description="データが空かどうか")


class FundamentalsOverview(BaseModel):
    """取得したファンダメンタル情報の概要。"""
    shares_outstanding: Optional[float] = None
    book_value_per_share: Optional[float] = None
    eps_ttm: Optional[float] = None
    sector: Optional[str] = None
    long_name: Optional[str] = None


class SectorPeersOverview(BaseModel):
    """セクター・ピア銘柄の概要。"""
    resolved_sector: Optional[str] = Field(None, description="解決したセクター名")
    peer_count: int = Field(0, description="ピア銘柄数")
    peer_tickers: list[str] = Field(default_factory=list, description="ピア銘柄ティッカー一覧")
    peer_pb_count: int = Field(0, description="PB取得できたピア数")
    peer_pe_count: int = Field(0, description="PE取得できたピア数")


class DataOverview(BaseModel):
    """データ取得フェーズの全概要（実行状況・データの要約）。"""
    price_history: Optional[PriceHistoryOverview] = Field(
        None, description="対象銘柄の株価履歴概要"
    )
    benchmark: Optional[PriceHistoryOverview] = Field(
        None, description="ベンチマーク株価履歴概要"
    )
    fundamentals: Optional[FundamentalsOverview] = Field(
        None, description="ファンダメンタル概要"
    )
    sector_peers: Optional[SectorPeersOverview] = Field(
        None, description="セクター・ピア概要"
    )
    value_inputs: Optional[dict[str, Any]] = Field(
        None, description="Value計算用の中間値（target_pb, target_pe 等）"
    )


class Scores(BaseModel):
    value_score: Optional[float] = Field(None, description="動的バリュースコア（0-100）")
    safety_score: Optional[float] = Field(None, description="財務安定性スコア（0-100）")
    momentum_score: Optional[float] = Field(None, description="モメンタムスコア（0-100）")
    total_score: Optional[float] = Field(None, description="総合スコア（0-100）")


class MarketLinkage(BaseModel):
    benchmark: str = Field(..., description="ベンチマーク名（例: TOPIX）")
    beta: Optional[float] = Field(None, description="ベータ値")
    r_squared: Optional[float] = Field(None, description="決定係数 R^2")
    alpha: Optional[float] = Field(None, description="アルファ（超過収益）")


class RiskMetrics(BaseModel):
    atr_percent: Optional[float] = Field(None, description="ATRベースの平均変動幅（%）")


class AiAnalysis(BaseModel):
    catalyst_summary: Optional[str] = Field(
        None, description="反転要因・カタリストの要約"
    )
    stop_loss_recommendation: Optional[float] = Field(
        None, description="推奨損切りラインの株価"
    )
    warning_flag: Optional[bool] = Field(
        None, description="定性的に致命的な懸念がある場合に true"
    )


class DvcScoreOutput(BaseModel):
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None

    scores: Scores
    market_linkage: MarketLinkage
    risk_metrics: RiskMetrics
    ai_analysis: AiAnalysis
    data_overview: Optional[DataOverview] = Field(
        None, description="データ取得の概要（取得日数・範囲・ファンダメンタル等）"
    )


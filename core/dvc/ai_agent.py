from __future__ import annotations

import json
import os
from typing import Any, Optional

from core.dvc.schema import AiAnalysis, MarketLinkage, RiskMetrics, Scores
from core.dvc.indicators import MomentumSignals, ValueSignals


def _build_prompt(
    ticker: str,
    name: Optional[str],
    sector: Optional[str],
    scores: Scores,
    market_linkage: MarketLinkage,
    risk_metrics: RiskMetrics,
    value_signals: ValueSignals,
    momentum_signals: MomentumSignals,
) -> str:
    lines: list[str] = []
    lines.append("あなたは日本株のクオンツ運用チームのリスク管理担当アナリストです。")
    lines.append("以下の数理スコアと指標から、カタリスト要約と損切りライン、警告フラグを検討してください。")
    lines.append("")
    lines.append(f"銘柄: {ticker} ({name or 'N/A'})")
    lines.append(f"セクター: {sector or 'N/A'}")
    lines.append("")
    lines.append("【スコア】")
    lines.append(f"- Value Score: {scores.value_score}")
    lines.append(f"- Safety Score: {scores.safety_score}")
    lines.append(f"- Momentum Score: {scores.momentum_score}")
    lines.append(f"- Total Score: {scores.total_score}")
    lines.append("")
    lines.append("【市場連動性】")
    lines.append(f"- Benchmark: {market_linkage.benchmark}")
    lines.append(f"- Beta: {market_linkage.beta}")
    lines.append(f"- R^2: {market_linkage.r_squared}")
    lines.append(f"- Alpha: {market_linkage.alpha}")
    lines.append("")
    lines.append("【リスク指標】")
    lines.append(f"- ATR%: {risk_metrics.atr_percent}")
    lines.append("")
    lines.append("【バリューシグナル（Zスコア）】")
    lines.append(
        f"- time_z_pb: {value_signals.time_z_pb}, time_z_pe: {value_signals.time_z_pe}"
    )
    lines.append(
        f"- space_z_pb: {value_signals.space_z_pb}, space_z_pe: {value_signals.space_z_pe}"
    )
    lines.append("")
    lines.append("【モメンタムシグナル】")
    lines.append(
        f"- MACDゴールデンクロスからの日数: {momentum_signals.macd_cross_recent_days}"
    )
    lines.append(f"- MACDクロス時の傾き: {momentum_signals.macd_slope_at_cross}")
    lines.append(f"- 出来高Zスコア: {momentum_signals.volume_z}")
    lines.append("")
    lines.append(
        "出力は必ず次のJSON形式で返してください："
        '{"catalyst_summary": string, "stop_loss_recommendation": number|null, "warning_flag": boolean}. '
        "catalyst_summaryは日本語で200文字以内、warning_flagは重大な定性リスクがあればtrue、それ以外はfalseとしてください。"
        "stop_loss_recommendationは現在株価から1〜1.5ATR分下のあたりを目安に、数値だけで返してください。"
    )
    return "\n".join(lines)


def _call_openai(prompt: str) -> AiAnalysis:
    try:
        from openai import OpenAI
    except ImportError:
        return AiAnalysis(
            catalyst_summary="OpenAIクライアントがインストールされていないため、定型メッセージを返します。",
            stop_loss_recommendation=None,
            warning_flag=None,
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return AiAnalysis(
            catalyst_summary="OPENAI_API_KEYが未設定のため、定型メッセージを返します。",
            stop_loss_recommendation=None,
            warning_flag=None,
        )

    client = OpenAI(api_key=api_key)
    # Chat Completions API（JSON 形式で返す）
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    content = (resp.choices[0].message.content or "").strip()
    if not content:
        return AiAnalysis(
            catalyst_summary="LLM応答が空でした。",
            stop_loss_recommendation=None,
            warning_flag=None,
        )
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        return AiAnalysis(
            catalyst_summary="LLM応答の解析に失敗したため、定型メッセージを返します。",
            stop_loss_recommendation=None,
            warning_flag=None,
        )
    # キー名のゆれ（snake_case / camelCase）に対応
    catalyst = _get_str(data, "catalyst_summary", "catalystSummary")
    stop_loss = _get_number(data, "stop_loss_recommendation", "stopLossRecommendation")
    warning = _get_bool(data, "warning_flag", "warningFlag")
    return AiAnalysis(
        catalyst_summary=catalyst,
        stop_loss_recommendation=stop_loss,
        warning_flag=warning,
    )


def _get_str(obj: dict[str, Any], *keys: str) -> Optional[str]:
    for k in keys:
        v = obj.get(k)
        if v is not None and isinstance(v, str):
            return v.strip() or None
    return None


def _get_number(obj: dict[str, Any], *keys: str) -> Optional[float]:
    for k in keys:
        v = obj.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _get_bool(obj: dict[str, Any], *keys: str) -> Optional[bool]:
    for k in keys:
        v = obj.get(k)
        if v is not None and isinstance(v, bool):
            return v
        if v is not None and isinstance(v, str):
            if v.strip().lower() in ("true", "1", "yes"):
                return True
            if v.strip().lower() in ("false", "0", "no"):
                return False
    return None


def generate_ai_analysis(
    ticker: str,
    name: Optional[str],
    sector: Optional[str],
    scores: Scores,
    market_linkage: MarketLinkage,
    risk_metrics: RiskMetrics,
    value_signals: ValueSignals,
    momentum_signals: MomentumSignals,
) -> AiAnalysis:
    prompt = _build_prompt(
        ticker=ticker,
        name=name,
        sector=sector,
        scores=scores,
        market_linkage=market_linkage,
        risk_metrics=risk_metrics,
        value_signals=value_signals,
        momentum_signals=momentum_signals,
    )
    # Phase 1ではOpenAIのみサポートする簡易実装
    return _call_openai(prompt)


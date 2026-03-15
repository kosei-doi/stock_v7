from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import math
import numpy as np
import pandas as pd
import yfinance as yf

from core.dvc.schema import (
    AiAnalysis,
    DataOverview,
    DvcScoreOutput,
    FundamentalsOverview,
    MarketLinkage,
    PriceHistoryOverview,
    RiskMetrics,
    Scores,
    SectorPeersOverview,
)
from core.dvc.data_fetcher import (
    FundamentalSnapshot,
    fetch_benchmark_history,
    fetch_fundamentals,
    fetch_price_history,
    fetch_sector_peers_map,
    get_sector_peers,
)
from core.dvc.indicators import (
    MarketRiskSignals,
    MomentumSignals,
    ValueSignals,
    compute_atr_percent,
    compute_beta_and_r2,
    compute_macd,
    compute_value_space_zscores,
    compute_value_time_zscores,
    compute_volume_zscore,
    detect_macd_cross,
)


def _map_z_to_score(z: Optional[float], low_is_good: bool = True) -> Optional[float]:
    """Zスコアから0〜100点にマッピングする関数（z=0を中立点=50点とする）。"""
    if z is None:
        return None

    # z=0 -> 50点, |z|=2 -> 90/10点 になるよう線形マッピング
    #  score = 50 - 20 * z  （low_is_good=True のとき）
    #  score = 50 + 20 * z  （low_is_good=False のとき）
    if low_is_good:
        score = 50.0 - 20.0 * float(z)
    else:
        score = 50.0 + 20.0 * float(z)

    # 0〜100にクリップ
    if score < 0.0:
        score = 0.0
    elif score > 100.0:
        score = 100.0
    return float(score)


def _combine_scores(values: list[Optional[float]], weights: list[float]) -> Optional[float]:
    if len(values) != len(weights):
        raise ValueError("values と weights の長さが一致しません")
    total_w = 0.0
    acc = 0.0
    for v, w in zip(values, weights):
        if v is None:
            continue
        acc += v * w
        total_w += w
    if total_w == 0:
        return None
    return float(acc / total_w)


def _score_momentum(signals: MomentumSignals) -> Optional[float]:
    parts: list[Optional[float]] = []
    weights: list[float] = []

    # MACDゴールデンクロスの鮮度（新しいほど高得点）
    if signals.macd_cross_recent_days is not None:
        d = float(signals.macd_cross_recent_days)
        # 0日で100点、日数が経つほど指数的に減衰する連続スコア。
        # time_scale を大きくすると減衰がゆるやかになる。
        time_scale = 10.0
        freshness = math.exp(-max(0.0, d) / time_scale)
        macd_score = float(100.0 * freshness)
        parts.append(macd_score)
        weights.append(0.5)

    # 出来高Zスコア（2σ以上で高評価）
    if signals.volume_z is not None:
        vol_score = _map_z_to_score(signals.volume_z, low_is_good=False)
        parts.append(vol_score)
        weights.append(0.5)

    return _combine_scores(parts, weights)


def _score_safety(f_score: Optional[float], altman_z: Optional[float]) -> Optional[float]:
    parts: list[Optional[float]] = []
    weights: list[float] = []

    if f_score is not None:
        parts.append(float(f_score / 9.0 * 100.0))
        weights.append(0.7)

    if altman_z is not None:
        # Altman Z を 1.8（ディストレス境界）を基準に正規化し、
        # 疑似 Z スコアとして 0〜100 の連続スコアに変換する。
        # 1.8 未満: マイナス側（低スコア）、3.0 以上: プラス側（高スコア）として扱う。
        denom = 1.2  # 1.8〜3.0 の幅をおおよその 1σ 相当として扱う
        z_norm = (float(altman_z) - 1.8) / denom
        s_altman = _map_z_to_score(z_norm, low_is_good=False)
        parts.append(s_altman)
        weights.append(0.3)

    return _combine_scores(parts, weights)


def _compute_simple_f_score(ticker: str) -> Optional[float]:
    """
    簡易版ピオトロスキーFスコア。
    本来は前年との比較が必要だが、Phase 1ではスナップショット指標を用いた近似とし、
    0〜9点スケールに正規化して返す。
    """
    tk = yf.Ticker(ticker)
    info = tk.info or {}

    signals: list[Optional[bool]] = []

    # 1) ROA > 0
    net_income = info.get("netIncomeToCommon") or info.get("netIncome")
    total_assets = info.get("totalAssets")
    roa_pos = None
    if net_income is not None and total_assets:
        try:
            roa_pos = float(net_income) / float(total_assets) > 0
        except (TypeError, ZeroDivisionError, ValueError):
            roa_pos = None
    signals.append(roa_pos)

    # 2) 営業CF > 0
    operating_cf = info.get("operatingCashflow")
    op_cf_pos = None
    if operating_cf is not None:
        try:
            op_cf_pos = float(operating_cf) > 0
        except (TypeError, ValueError):
            op_cf_pos = None
    signals.append(op_cf_pos)

    # 3) レバレッジが過度でない（総資産に対する負債が80%未満）
    total_liab = info.get("totalLiab")
    leverage_ok = None
    if total_liab is not None and total_assets:
        try:
            leverage_ok = float(total_liab) / float(total_assets) < 0.8
        except (TypeError, ZeroDivisionError, ValueError):
            leverage_ok = None
    signals.append(leverage_ok)

    # 4) 流動比率 > 1
    current_assets = info.get("totalCurrentAssets")
    current_liab = info.get("totalCurrentLiabilities")
    current_ratio_ok = None
    if current_assets is not None and current_liab:
        try:
            current_ratio_ok = float(current_assets) / float(current_liab) > 1.0
        except (TypeError, ZeroDivisionError, ValueError):
            current_ratio_ok = None
    signals.append(current_ratio_ok)

    # 5) 粗利率が正（粗利/売上 > 0）
    gross_profit = info.get("grossProfits")
    revenue = info.get("totalRevenue")
    margin_ok = None
    if gross_profit is not None and revenue:
        try:
            margin_ok = float(gross_profit) / float(revenue) > 0
        except (TypeError, ZeroDivisionError, ValueError):
            margin_ok = None
    signals.append(margin_ok)

    # 有効なシグナルだけでスコアを作る
    valid = [s for s in signals if s is not None]
    if not valid:
        return None
    raw_score = sum(1 for s in valid if s)
    # 有効な項目数に応じて0〜9にスケール
    normalized = 9.0 * raw_score / len(valid)
    return float(normalized)


def _compute_simple_altman_z(
    ticker: str, price_df: pd.DataFrame, fundamentals: FundamentalSnapshot
) -> Optional[float]:
    """
    簡易Altman Zスコア。
    yfinance.infoに十分な項目がある場合のみ計算し、足りなければNoneを返す。
    """
    tk = yf.Ticker(ticker)
    info = tk.info or {}

    total_assets = info.get("totalAssets")
    total_liab = info.get("totalLiab")
    retained_earnings = info.get("retainedEarnings")
    ebit = info.get("ebit")
    sales = info.get("totalRevenue")

    if not total_assets or not total_liab or not sales or ebit is None:
        return None

    try:
        ta = float(total_assets)
        tl = float(total_liab)
        re = float(retained_earnings) if retained_earnings is not None else 0.0
        ebit_val = float(ebit)
        sales_val = float(sales)
    except (TypeError, ValueError):
        return None

    # 株式の時価総額（Market Value of Equity）
    last_close_val = price_df["close"].iloc[-1] if not price_df.empty else None
    if isinstance(last_close_val, pd.Series):
        last_close_val = last_close_val.iloc[0]
    try:
        price = float(last_close_val) if last_close_val is not None else None
    except (TypeError, ValueError):
        price = None

    if price is None or not fundamentals.shares_outstanding:
        return None

    try:
        mve = price * float(fundamentals.shares_outstanding)
    except (TypeError, ValueError):
        return None

    if ta == 0 or tl == 0:
        return None

    x1 = (float(info.get("workingCapital", 0.0)) / ta) if ta else 0.0
    x2 = re / ta
    x3 = ebit_val / ta
    x4 = mve / tl
    x5 = sales_val / ta

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    return float(z)


def _df_to_price_overview(df: pd.DataFrame) -> PriceHistoryOverview:
    """DataFrame（株価履歴）から PriceHistoryOverview を生成。"""
    if df is None or df.empty:
        return PriceHistoryOverview(rows=0, columns=[], empty=True)
    index = df.index
    date_min = str(index.min()) if len(index) else None
    date_max = str(index.max()) if len(index) else None
    # カラム名は MultiIndex の場合は先頭要素のみ文字列化
    col_names = [str(c[0]) if isinstance(c, tuple) else str(c) for c in df.columns]
    last_close = None
    close_col = None
    for c in df.columns:
        if (isinstance(c, tuple) and c[0] == "close") or c == "close":
            close_col = c
            break
    if close_col is not None:
        last_val = df[close_col].iloc[-1]
        if isinstance(last_val, pd.Series):
            last_val = last_val.iloc[0]
        last_close = float(last_val) if last_val is not None else None
    return PriceHistoryOverview(
        rows=len(df),
        date_min=date_min,
        date_max=date_max,
        columns=col_names,
        last_close=last_close,
        empty=False,
    )


def _build_data_overview(
    price_df: pd.DataFrame,
    bench_df: pd.DataFrame,
    fundamentals: FundamentalSnapshot,
    resolved_sector: Optional[str],
    peers: list[str],
    peer_pb_count: int,
    peer_pe_count: int,
    target_pb: Optional[float],
    target_pe: Optional[float],
    time_z_pb: Optional[float],
    time_z_pe: Optional[float],
    space_z_pb: Optional[float],
    space_z_pe: Optional[float],
) -> DataOverview:
    """データ取得フェーズの全概要を組み立てる。"""
    return DataOverview(
        price_history=_df_to_price_overview(price_df),
        benchmark=_df_to_price_overview(bench_df),
        fundamentals=FundamentalsOverview(
            shares_outstanding=fundamentals.shares_outstanding,
            book_value_per_share=fundamentals.book_value_per_share,
            eps_ttm=fundamentals.eps_ttm,
            sector=fundamentals.sector,
            long_name=fundamentals.long_name,
        ),
        sector_peers=SectorPeersOverview(
            resolved_sector=resolved_sector,
            peer_count=len(peers),
            peer_tickers=peers,
            peer_pb_count=peer_pb_count,
            peer_pe_count=peer_pe_count,
        ),
        value_inputs={
            "target_pb": target_pb,
            "target_pe": target_pe,
            "time_z_pb": time_z_pb,
            "time_z_pe": time_z_pe,
            "space_z_pb": space_z_pb,
            "space_z_pe": space_z_pe,
        },
    )


def run_dvc_for_ticker(
    ticker: str,
    benchmark_ticker: str,
    years: int,
    sector_peers_path: str,
    llm_enabled: bool = False,
    llm_client: object | None = None,
    bench_df: pd.DataFrame | None = None,
    peers_data: dict | None = None,
) -> DvcScoreOutput:
    # 1. データ取得（個別銘柄は常に都度取得；マクロ・ピアは呼び出し元でキャッシュ済みの場合は渡される）
    price_df = fetch_price_history(ticker, years)
    if bench_df is not None:
        pass  # キャッシュまたは呼び出し元で取得済み
    else:
        bench_df = fetch_benchmark_history(benchmark_ticker, years)
    fundamentals: FundamentalSnapshot = fetch_fundamentals(ticker)

    peers_map = fetch_sector_peers_map(sector_peers_path)
    resolved_sector, peers = get_sector_peers(fundamentals.sector, peers_map)

    # 2. Valueモジュールのための指標計算
    time_z_pb, time_z_pe = compute_value_time_zscores(
        price_df,
        fundamentals.book_value_per_share,
        fundamentals.eps_ttm,
    )

    # 対象銘柄の現在PB, PE
    last_close_val = price_df["close"].iloc[-1] if not price_df.empty else None
    if isinstance(last_close_val, pd.Series):
        last_close_val = last_close_val.iloc[0]
    last_close = float(last_close_val) if last_close_val is not None else None

    target_pb = None
    if (
        last_close is not None
        and fundamentals.book_value_per_share
        and fundamentals.book_value_per_share != 0
    ):
        target_pb = float(last_close / float(fundamentals.book_value_per_share))

    target_pe = None
    if last_close is not None and fundamentals.eps_ttm and fundamentals.eps_ttm != 0:
        target_pe = float(last_close / float(fundamentals.eps_ttm))

    peer_pbs: list[float] = []
    peer_pes: list[float] = []
    if peers:
        # キャッシュ済み peers_data があればそれを使用、なければ yfinance で都度取得
        for code in peers:
            if peers_data and code in peers_data:
                info = peers_data[code]
                bv = info.get("bookValue")
                eps_ttm = info.get("trailingEps")
                price = info.get("currentPrice")
            else:
                import yfinance as yf

                info = (yf.Ticker(code).info or {})
                bv = info.get("bookValue")
                eps_ttm = info.get("trailingEps")
                price = info.get("currentPrice")
            if price and bv:
                try:
                    peer_pbs.append(float(price / bv))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            if price and eps_ttm:
                try:
                    peer_pes.append(float(price / eps_ttm))
                except (TypeError, ValueError, ZeroDivisionError):
                    pass

    space_z_pb, space_z_pe = compute_value_space_zscores(
        target_pb, target_pe, peer_pbs, peer_pes
    )

    value_time_score_pb = _map_z_to_score(time_z_pb, low_is_good=True)
    value_time_score_pe = _map_z_to_score(time_z_pe, low_is_good=True)
    value_space_score_pb = _map_z_to_score(space_z_pb, low_is_good=True)
    value_space_score_pe = _map_z_to_score(space_z_pe, low_is_good=True)

    value_score_time = _combine_scores(
        [value_time_score_pb, value_time_score_pe], [0.5, 0.5]
    )
    value_score_space = _combine_scores(
        [value_space_score_pb, value_space_score_pe], [0.5, 0.5]
    )
    value_score = _combine_scores(
        [value_score_time, value_score_space], [0.6, 0.4]
    )

    # 3. Safetyモジュール（簡略版）
    f_score = _compute_simple_f_score(ticker)
    altman_z = _compute_simple_altman_z(ticker, price_df, fundamentals)
    safety_score = _score_safety(f_score, altman_z)

    # 4. Momentumモジュール
    macd_cross_recent_days, macd_slope_at_cross = None, None
    volume_z = None
    if not price_df.empty:
        macd_cross_recent_days, macd_slope_at_cross = detect_macd_cross(price_df)
        volume_z = compute_volume_zscore(price_df)
    momentum_signals = MomentumSignals(
        macd_cross_recent_days=macd_cross_recent_days,
        macd_slope_at_cross=macd_slope_at_cross,
        volume_z=volume_z,
    )
    momentum_score = _score_momentum(momentum_signals)

    # 5. Market & Riskモジュール
    beta, r_squared, alpha = (
        (None, None, None)
        if price_df.empty or bench_df.empty
        else compute_beta_and_r2(price_df, bench_df)
    )
    atr_percent = compute_atr_percent(price_df) if not price_df.empty else None

    market_risk = MarketRiskSignals(
        beta=beta, r_squared=r_squared, alpha=alpha, atr_percent=atr_percent
    )

    # 6. 総合スコア
    total_score = _combine_scores(
        [value_score, safety_score, momentum_score], [0.4, 0.4, 0.2]
    )

    scores = Scores(
        value_score=value_score,
        safety_score=safety_score,
        momentum_score=momentum_score,
        total_score=total_score,
    )

    market_linkage = MarketLinkage(
        benchmark=benchmark_ticker,
        beta=market_risk.beta,
        r_squared=market_risk.r_squared,
        alpha=market_risk.alpha,
    )

    risk_metrics = RiskMetrics(atr_percent=market_risk.atr_percent)

    # 7. LLMによる ai_analysis（Phase 1ではオプション）。llm_client は未使用時は None でよく、ai_agent が環境変数で API を呼ぶ。
    if llm_enabled:
        from core.dvc.ai_agent import generate_ai_analysis

        ai_analysis = generate_ai_analysis(
            ticker=ticker,
            name=fundamentals.long_name,
            sector=resolved_sector or fundamentals.sector,
            scores=scores,
            market_linkage=market_linkage,
            risk_metrics=risk_metrics,
            value_signals=ValueSignals(
                time_z_pb=time_z_pb,
                time_z_pe=time_z_pe,
                space_z_pb=space_z_pb,
                space_z_pe=space_z_pe,
            ),
            momentum_signals=momentum_signals,
        )
    else:
        ai_analysis = AiAnalysis(
            catalyst_summary="LLM未使用モードのため簡易出力です。",
            stop_loss_recommendation=None,
            warning_flag=None,
        )

    # データ取得概要を組立（実行状況・全データの要約）
    data_overview = _build_data_overview(
        price_df=price_df,
        bench_df=bench_df,
        fundamentals=fundamentals,
        resolved_sector=resolved_sector,
        peers=peers,
        peer_pb_count=len(peer_pbs),
        peer_pe_count=len(peer_pes),
        target_pb=target_pb,
        target_pe=target_pe,
        time_z_pb=time_z_pb,
        time_z_pe=time_z_pe,
        space_z_pb=space_z_pb,
        space_z_pe=space_z_pe,
    )

    return DvcScoreOutput(
        ticker=ticker,
        name=fundamentals.long_name,
        sector=resolved_sector or fundamentals.sector,
        scores=scores,
        market_linkage=market_linkage,
        risk_metrics=risk_metrics,
        ai_analysis=ai_analysis,
        data_overview=data_overview,
    )


"""
日次バッチ統合: データ取得 → DVCスコア更新 → マクロ判定 → パージ → ドラフト → レポート出力。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.utils.config_loader import get_validated_config, load_config
from core.dpa.dpa_draft import LOT_SIZE, run_draft
from core.dpa.dpa_macro import get_macro_state
from core.dpa.dpa_portfolio_score import compute_portfolio_total_score
from core.dpa.dpa_scores import compute_score_trend, load_scores_history
from core.dpa.dpa_weights import compute_target_weights
from core.dpa.dpa_purge import run_purge
from core.dpa.dpa_schema import DpaDailyReport
from core.utils.daily_cache import (
    DEFAULT_CACHE_PATH,
    DEFAULT_CACHE_CUTOFF_HOUR,
    DEFAULT_CACHE_CUTOFF_MINUTE,
    DEFAULT_MARKET_TZ,
    get_macro_and_peers_data,
    _now_jst,
)
from core.dvc.dvc_batch import run_dvc_for_watchlist
from core.dvc.schema import DvcScoreOutput
from core.utils.watchlist_io import (
    WATCHLIST_PATH,
    get_holdings,
    get_watching,
    load_watchlist,
    positions_from_watchlist,
    _ticker,
)

PORTFOLIO_STATE_PATH = "portfolio_state.json"
DEFAULT_TOTAL_CAPITAL_JPY = 5_000_000


def _resolve_path(path_str: str) -> str:
    return str(Path(path_str).resolve())


def _progress(step: int, total: int, message: str, *, verbose_msg: Optional[str] = None, verbose: bool = False) -> None:
    """ステップ進行を stderr に表示する。"""
    print(f"  [{step}/{total}] {message}", file=sys.stderr)
    if verbose and verbose_msg:
        print(f"        {verbose_msg}", file=sys.stderr)


def load_portfolio_state(path: str = PORTFOLIO_STATE_PATH) -> dict:
    """現金残高などを読む。"""
    p = Path(path)
    if not p.exists():
        return {"cash_yen": DEFAULT_TOTAL_CAPITAL_JPY}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cash_yen": DEFAULT_TOTAL_CAPITAL_JPY}


def current_prices_from_dvc_results(results: dict[str, DvcScoreOutput]) -> dict[str, float]:
    """DVC 結果から銘柄ごとの直近終値を取得。"""
    out = {}
    for ticker, d in results.items():
        if d.data_overview and d.data_overview.price_history and d.data_overview.price_history.last_close is not None:
            out[ticker] = float(d.data_overview.price_history.last_close)
    return out


def holdings_value(holdings: list[dict], positions: dict, current_prices: dict[str, float]) -> float:
    """保有評価額の合計。"""
    total = 0.0
    for h in holdings:
        t = _ticker(h)
        if not t:
            continue
        pos = positions.get(t) or {}
        shares = pos.get("shares") or pos.get("shares_held") or 0
        price = current_prices.get(t)
        if price is not None and shares:
            total += float(shares) * float(price)
    return total


def current_weights(
    holdings: list[dict],
    positions: dict,
    current_prices: dict[str, float],
    cash_current: float,
) -> tuple[dict[str, float], float]:
    """銘柄ごとの現在構成比と総資産（現金+保有評価額）を返す。"""
    values: dict[str, float] = {}
    total_equity = 0.0
    for h in holdings:
        t = _ticker(h)
        if not t:
            continue
        pos = positions.get(t) or {}
        shares = pos.get("shares") or pos.get("shares_held") or 0
        price = current_prices.get(t)
        if price is None or shares <= 0:
            continue
        v = float(shares) * float(price)
        values[t] = v
        total_equity += v
    total_cap = cash_current + total_equity
    weights = {t: (v / total_cap) for t, v in values.items()} if total_cap > 0 else {t: 0.0 for t in values.keys()}
    return weights, total_cap


def build_holdings_list(watchlist: list[dict], positions: dict) -> list[dict]:
    """HOLDING 銘柄の一覧を positions の情報付きで返す。"""
    holdings = get_holdings(watchlist)
    out = []
    for h in holdings:
        t = _ticker(h)
        pos = positions.get(t) or {}
        out.append({
            "ticker": t,
            "ticker_symbol": t,
            "shares": pos.get("shares") or pos.get("shares_held") or 0,
        })
    return out


def format_report(report: DpaDailyReport) -> str:
    """プレーンテキストの日次レポートを生成。"""
    lines = [
        "========== DPA 日次レポート ==========",
        "",
        f"## 本日の目標現金比率: {report.target_cash_ratio * 100:.0f}%",
        f"## マクロフェーズ: {report.phase_name_ja}",
        f"  - VI Zスコア: {report.vi_z if report.vi_z is not None else '-'}",
        f"  - MACDトレンド: {report.macd_trend if report.macd_trend is not None else '-'}",
        "",
        "## ポートフォリオ概要",
        f"  - 総資産: {report.total_capital_yen:,.0f} 円" if report.total_capital_yen is not None else "  - 総資産: -",
        f"  - 現金: {report.cash_yen:,.0f} 円" if report.cash_yen is not None else "  - 現金: -",
        f"  - 株式評価額: {report.equity_value_yen:,.0f} 円" if report.equity_value_yen is not None else "  - 株式評価額: -",
    ]
    # 新規購入予算（理論値と防御適用後の実際の値）の表示
    raw_budget = report.draft.raw_available_budget
    effective_budget = report.draft.available_budget
    if raw_budget is not None and raw_budget != effective_budget:
        lines.append(f"  - 本日新規購入に使える理論上の最大額: {raw_budget:,.0f} 円")
        lines.append(f"  - マクロ防衛モードにより実際の新規購入枠: {effective_budget:,.0f} 円")
    else:
        lines.append(f"  - 本日新規購入に使える新規購入枠: {effective_budget:,.0f} 円")
    lines.append("")
    lines.append("## 売却指示")
    if not report.purge.items:
        lines.append("  （なし）")
    else:
        for it in report.purge.items:
            lines.append(f"  - {it.ticker}: {it.reason_ja} (現在価格: {it.current_price})")
    lines.append("")
    # 保有銘柄の状況（現在比率・目標比率・スコアトレンド・株価・ロット必要資金）
    cw = report.current_weights or {}
    tw = report.target_weights or {}
    st_all = report.score_trends or {}
    names = report.ticker_names or {}
    prices = report.last_prices or {}
    holding_tickers = [t for t, w in cw.items() if w > 0]
    if holding_tickers:
        lines.append("## 保有銘柄の状況")
        # 揃えやすいようにカラム幅を固定して整形
        for ticker in sorted(holding_tickers):
            w_cur = cw.get(ticker, 0.0)
            w_star = tw.get(ticker, 0.0)
            st = st_all.get(ticker) or {}
            last = st.get("last")
            level = st.get("level")
            trend = st.get("trend")
            name = names.get(ticker, "") or "-"
            price = prices.get(ticker)

            ticker_col = f"{ticker:<8}"
            name_col = f"{name:<40.40}"
            cur_col = f"{w_cur*100:>5.1f}%"
            tgt_col = f"{w_star*100:>5.1f}%"
            score_col = f"{last:>6.1f}" if last is not None else f"{'-':>6}"
            level_col = f"{level:>4.2f}" if level is not None else f"{'-':>4}"
            trend_col = f"{trend:>4.2f}" if trend is not None else f"{'-':>4}"
            price_col = f"{price:>8.0f} 円" if price is not None else "   -"

            lines.append(
                f"  - {ticker_col} {name_col} "
                f"現在={cur_col}  目標={tgt_col}  "
                f"score={score_col}  level={level_col}  trend={trend_col}  株価={price_col}"
            )
        lines.append("")

    # ウォッチリスト優先度（ポートフォリオ用 total_score 順＝購入優先順）
    if tw:
        lines.append("## ウォッチリスト優先度（保有すべき順）")
        ps = report.portfolio_scores or {}
        ordered = sorted(tw.keys(), key=lambda t: (ps.get(t) or 0.0, tw.get(t) or 0.0), reverse=True)
        for ticker in ordered:
            status = "HOLDING" if cw.get(ticker, 0.0) > 0 else "WATCHING"
            st = st_all.get(ticker) or {}
            last = st.get("last")
            trend = st.get("trend")
            name = names.get(ticker, "") or "-"
            price = prices.get(ticker)

            ticker_col = f"{ticker:<8}"
            name_col = f"{name:<40.40}"
            status_col = f"{status:<8}"
            score_col = f"{last:>6.1f}" if last is not None else f"{'-':>6}"
            trend_col = f"{trend:>4.2f}" if trend is not None else f"{'-':>4}"
            price_col = f"{price:>8.0f} 円" if price is not None else "   -"

            lines.append(
                f"  - {ticker_col} {name_col} [{status_col}] "
                f"score={score_col}  trend={trend_col}  株価={price_col}"
            )
        lines.append("")

    lines.append("## 新規購入推奨")
    if not report.draft.recommendations:
        lines.append("  （なし）")
    else:
        lines.append(f"  空き予算: {report.draft.available_budget:,.0f} 円")
        for r in report.draft.recommendations:
            lines.append(f"  - {r.ticker} ({r.name or '-'}): {r.shares} 株 (予算: {r.budget_used:,.0f} 円)")
    lines.append("")
    lines.append("======================================")
    return "\n".join(lines)


def run_daily_routine(
    watchlist_path: str = WATCHLIST_PATH,
    sector_peers_path: str = "data/sector_peers.json",
    benchmark_ticker: str = "1306.T",
    years: int = 5,
    output_dir: str = "output",
    cache_path: str = DEFAULT_CACHE_PATH,
    portfolio_path: str = PORTFOLIO_STATE_PATH,
    vi_value_override: Optional[float] = None,
    vi_ticker: Optional[str] = None,
    mu_cash: float = 0.4,
    a_vi: float = 0.1,
    b_macd: float = 0.1,
    macd_scale: float = 0.002,
    min_cash_ratio: float = 0.2,
    max_cash_ratio: float = 0.8,
    momentum_threshold: float = 50.0,
    lot_size: int = LOT_SIZE,
    llm_enabled: bool = False,
    verbose: bool = False,
    cache_cutoff_hour: int = DEFAULT_CACHE_CUTOFF_HOUR,
    cache_cutoff_minute: int = DEFAULT_CACHE_CUTOFF_MINUTE,
    market_tz: str = DEFAULT_MARKET_TZ,
    scores_history_path: str = "data/scores_history.json",
) -> DpaDailyReport:
    """
    日次ルーチンを一括実行し、DpaDailyReport を返す。
    キャッシュの更新可否は曜日・時刻を考慮する（daily_cache のスケジュール判定）。
    """
    now = _now_jst()
    # 論理日付: 6時区切り（現在時刻 JST から 6 時間引いた日付）
    data_date = (now - timedelta(hours=6)).date().isoformat()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S JST")
    total_steps = 7

    print("", file=sys.stderr)
    print("=== DPA 日次バッチ 開始 ===", file=sys.stderr)
    _progress(1, total_steps, "ウォッチリスト読込・企業分析（DVCスコア計算）…", verbose=verbose)
    results = run_dvc_for_watchlist(
        watchlist_path=watchlist_path,
        sector_peers_path=sector_peers_path,
        benchmark_ticker=benchmark_ticker,
        years=years,
        output_dir=output_dir,
        cache_path=cache_path,
        vi_ticker=vi_ticker,
        llm_enabled=llm_enabled,
        verbose=verbose,
        cache_now=now,
        cache_cutoff_hour=cache_cutoff_hour,
        cache_cutoff_minute=cache_cutoff_minute,
        cache_market_tz=market_tz,
        progress_callback=lambda msg: print(f"        {msg}", file=sys.stderr),
        scores_history_path=scores_history_path,
    )
    watchlist = load_watchlist(watchlist_path)
    if len(watchlist) == 0 and len(results) == 0:
        print("        → ウォッチリスト 0 件のためスキップ", file=sys.stderr)
    else:
        print(f"        → {len(results)} 銘柄のスコア計算完了", file=sys.stderr)

    _progress(2, total_steps, "ウォッチリスト・ポジション・現金の読込…", verbose=verbose)
    positions = positions_from_watchlist(path=watchlist_path)
    state = load_portfolio_state(portfolio_path)
    cash_current = float(state.get("cash_yen", DEFAULT_TOTAL_CAPITAL_JPY))
    current_prices = current_prices_from_dvc_results(results)
    holdings = build_holdings_list(watchlist, positions)
    holdings_val = holdings_value(holdings, positions, current_prices)
    current_w, total_cap_now = current_weights(holdings, positions, current_prices, cash_current)
    total_cap = total_cap_now  # 常に現金＋株式の実値を使用（config の total_capital は廃止）
    print(f"        → 保有 {len(holdings)} 銘柄, 総資産 {total_cap:,.0f} 円", file=sys.stderr)

    _progress(3, total_steps, "マクロ判定（ベンチマーク・VI・MACD → 目標現金比率）…", verbose=verbose)
    bench_df, _, vi_series = get_macro_and_peers_data(
        benchmark_ticker=benchmark_ticker,
        years=years,
        sector_peers_path=sector_peers_path,
        cache_path=cache_path,
        vi_ticker=vi_ticker,
        now=now,
        cutoff_hour=cache_cutoff_hour,
        cutoff_minute=cache_cutoff_minute,
        market_tz=market_tz,
    )
    # vi_value_override があれば優先し、なければ系列からZスコアベースで評価
    macro = get_macro_state(
        bench_df,
        vi_series=vi_series,
        mu_cash=mu_cash,
        a_vi=a_vi,
        b_macd=b_macd,
        macd_scale=macd_scale,
        min_cash_ratio=min_cash_ratio,
        max_cash_ratio=max_cash_ratio,
    )
    print(f"        → フェーズ: {macro.phase_name_ja}, 目標現金比率: {macro.target_cash_ratio*100:.0f}%", file=sys.stderr)

    _progress(4, total_steps, "スコアトレンド・ポートフォリオスコア・ターゲット構成比の計算…", verbose=verbose)
    history = load_scores_history(scores_history_path)
    score_trends: dict[str, dict] = {}
    for ticker in results.keys():
        score_trends[ticker] = compute_score_trend(ticker, history)
    portfolio_scores = {t: compute_portfolio_total_score(results[t], macro) for t in results}
    target_weights = compute_target_weights(results, score_trends, macro, portfolio_scores=portfolio_scores)
    print(f"        → ターゲット構成比を {len(target_weights)} 銘柄に割り当て完了", file=sys.stderr)

    _progress(5, total_steps, "パージ（売却候補の判定：オーバーウェイト銘柄の洗い出し）…", verbose=verbose)
    purge_out = run_purge(
        phase=macro.phase,
        holdings=holdings,
        current_weights=current_w,
        target_weights=target_weights,
        current_prices=current_prices,
    )
    print(f"        → 売却候補: {purge_out.total_count} 銘柄", file=sys.stderr)

    _progress(6, total_steps, "ドラフト（購入候補の判定：ポートフォリオスコア順・予算配分）…", verbose=verbose)
    watching_items = get_watching(watchlist)
    watching_snapshots = [results[_ticker(w)] for w in watching_items if _ticker(w) in results]
    draft_out = run_draft(
        macro_state=macro,
        total_capital=total_cap,
        cash_current=cash_current,
        holdings_value=holdings_val,
        holdings=holdings,
        watching_snapshots=watching_snapshots,
        current_prices=current_prices,
        target_weights=target_weights,
        current_weights=current_w,
        score_trends=score_trends,
        portfolio_scores=portfolio_scores,
        all_scores=results,
        momentum_threshold=momentum_threshold,
        lot_size=lot_size,
    )
    print(f"        → 購入候補: {len(draft_out.recommendations)} 件, 空き予算: {draft_out.available_budget:,.0f} 円", file=sys.stderr)

    _progress(7, total_steps, "レポート生成…", verbose=verbose)
    ticker_names = {t: results[t].name for t in results.keys()}

    # 総資産は常に「現金＋株式評価額」の実値（config の target ではない）
    total_actual = cash_current + holdings_val

    report = DpaDailyReport(
        created_at=created_at,
        data_date=data_date,
        target_cash_ratio=macro.target_cash_ratio,
        phase=macro.phase,
        phase_name_ja=macro.phase_name_ja,
        vi_z=macro.vi_z,
        macd_trend=macro.macd_trend,
        cash_yen=cash_current,
        total_capital_yen=total_actual,
        equity_value_yen=holdings_val,
        current_weights=current_w,
        target_weights=target_weights,
        score_trends=score_trends,
        portfolio_scores=portfolio_scores,
        ticker_names=ticker_names,
        last_prices=current_prices,
        purge=purge_out,
        draft=draft_out,
    )
    report.report_text = format_report(report)
    print("=== DPA 日次バッチ 完了 ===", file=sys.stderr)
    print("", file=sys.stderr)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DPA 日次バッチ")
    parser.add_argument("--config", help="設定ファイル（YAML）")
    parser.add_argument("--watchlist", default=WATCHLIST_PATH, help="ウォッチリストJSON")
    parser.add_argument("--output-dir", default="output", help="DVC 出力先")
    parser.add_argument("--vi", type=float, help="日経VI などVIの直近値（未指定時はヒストリのみで判定）")
    parser.add_argument("--no-llm", action="store_true", help="LLM を使わない")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv or [])

    cfg_path = Path(args.config) if args.config else None
    if cfg_path is not None and not cfg_path.exists():
        print(f"指定した設定ファイルがありません: {cfg_path}", file=sys.stderr)
    raw_cfg = load_config(cfg_path, use_example_as_base=True)
    cfg = get_validated_config(raw_cfg)

    sector_peers_path = _resolve_path(cfg.get("sector_peers_path", "data/sector_peers.json"))
    if not Path(sector_peers_path).exists():
        print(f"sector_peers が見つかりません: {sector_peers_path}", file=sys.stderr)
        return 1

    if args.verbose:
        print(
            f"        config={cfg_path or '(example only)'} cache_path={_resolve_path(cfg.get('cache_path', 'data/daily_cache.json'))} "
            f"sector_peers={sector_peers_path} "
            f"portfolio={_resolve_path(cfg.get('portfolio_path', PORTFOLIO_STATE_PATH))}",
            file=sys.stderr,
        )

    report = run_daily_routine(
        watchlist_path=args.watchlist,
        sector_peers_path=sector_peers_path,
        benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
        years=int(cfg.get("years", 5)),
        output_dir=str(cfg.get("output_dir", args.output_dir)),
        cache_path=_resolve_path(cfg.get("cache_path", "data/daily_cache.json")),
        portfolio_path=_resolve_path(cfg.get("portfolio_path", PORTFOLIO_STATE_PATH)),
        vi_value_override=args.vi,
        vi_ticker=cfg.get("vi_ticker"),
        mu_cash=float(cfg.get("mu_cash", 0.4)),
        a_vi=float(cfg.get("a_vi", 0.1)),
        b_macd=float(cfg.get("b_macd", 0.1)),
        macd_scale=float(cfg.get("macd_scale", 0.002)),
        min_cash_ratio=float(cfg.get("min_cash_ratio", 0.2)),
        max_cash_ratio=float(cfg.get("max_cash_ratio", 0.8)),
        momentum_threshold=float(cfg.get("momentum_threshold", 50.0)),
        lot_size=int(cfg.get("lot_size", LOT_SIZE)),
        llm_enabled=False if args.no_llm else bool(cfg.get("llm_enabled", False)),
        verbose=args.verbose,
        cache_cutoff_hour=int(cfg.get("cache_cutoff_hour", DEFAULT_CACHE_CUTOFF_HOUR)),
        cache_cutoff_minute=int(cfg.get("cache_cutoff_minute", DEFAULT_CACHE_CUTOFF_MINUTE)),
        market_tz=str(cfg.get("market_tz", DEFAULT_MARKET_TZ)),
        scores_history_path=_resolve_path(cfg.get("scores_history_path", "data/scores_history.json")),
    )

    last_report_path = Path("data/last_report.json")
    previous_report_path = Path("data/previous_report.json")
    last_report_path.parent.mkdir(parents=True, exist_ok=True)

    # 同日複数回実行を考慮: data_date が異なる場合のみ既存を previous に退避（日付なしの旧形式には補完する）
    if last_report_path.exists():
        try:
            existing = json.loads(last_report_path.read_text(encoding="utf-8"))
            existing_data_date = existing.get("data_date")
            if existing_data_date != report.data_date:
                # 退避用に created_at / data_date を補完（昨日のデータとして扱う）
                prev_data_date = existing_data_date
                prev_created_at = existing.get("created_at")
                if not prev_data_date:
                    try:
                        new_d = datetime.strptime(report.data_date, "%Y-%m-%d").date()
                        prev_data_date = (new_d - timedelta(days=1)).isoformat()
                    except (ValueError, TypeError):
                        prev_data_date = report.data_date
                if not prev_created_at:
                    prev_created_at = f"{prev_data_date} (前回実行)"
                out = dict(existing)
                out["created_at"] = prev_created_at
                out["data_date"] = prev_data_date
                previous_report_path.write_text(
                    json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        except (json.JSONDecodeError, OSError):
            pass

    try:
        last_report_path.write_text(
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"警告: last_report.json の書き込みに失敗しました: {e}", file=sys.stderr)

    print(report.report_text or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

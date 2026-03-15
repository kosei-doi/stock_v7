"""
ウォッチリスト全銘柄に対して DVC スコアを一括計算し、output/<ticker>.json に保存する。
日次バッチでマクロ・代表銘柄は1回だけ取得し、各銘柄は都度取得する流れを再利用する。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.utils.daily_cache import DEFAULT_CACHE_PATH, get_macro_and_peers_data, _now_jst
from core.dpa.dpa_scores import SCORES_HISTORY_PATH, update_scores_history_for_date
from core.utils.io_utils import save_output_json
from core.dvc.scoring import run_dvc_for_ticker
from core.dvc.schema import DvcScoreOutput
from core.utils.watchlist_io import load_watchlist, _ticker


def run_dvc_for_watchlist(
    watchlist_path: str = "data/watchlist.json",
    sector_peers_path: str = "data/sector_peers.json",
    benchmark_ticker: str = "1306.T",
    years: int = 5,
    output_dir: str = "output",
    cache_path: str = DEFAULT_CACHE_PATH,
    vi_ticker: Optional[str] = None,
    llm_enabled: bool = False,
    verbose: bool = False,
    cache_now: Optional[datetime] = None,
    cache_cutoff_hour: Optional[int] = None,
    cache_cutoff_minute: Optional[int] = None,
    cache_market_tz: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    scores_history_path: Optional[str] = None,
) -> dict[str, DvcScoreOutput]:
    """
    ウォッチリストに載っている全銘柄について DVC を実行し、
    output_dir/<ticker>.json に保存する。戻り値は ticker -> DvcScoreOutput。
    あわせて scores_history.json に当日分のスコア履歴を更新する。
    cache_now 等を渡すと、キャッシュの fresh 判定に曜日・時刻を反映する。
    """
    items = load_watchlist(watchlist_path)
    if not items:
        return {}

    kwargs: dict = {
        "benchmark_ticker": benchmark_ticker,
        "years": years,
        "sector_peers_path": sector_peers_path,
        "cache_path": cache_path,
        "vi_ticker": vi_ticker,
    }
    if cache_now is not None:
        kwargs["now"] = cache_now
        if cache_cutoff_hour is not None:
            kwargs["cutoff_hour"] = cache_cutoff_hour
        if cache_cutoff_minute is not None:
            kwargs["cutoff_minute"] = cache_cutoff_minute
        if cache_market_tz is not None:
            kwargs["market_tz"] = cache_market_tz
    if progress_callback is not None:
        kwargs["progress_callback"] = progress_callback
    bench_df, peers_data, _ = get_macro_and_peers_data(**kwargs)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    results: dict[str, DvcScoreOutput] = {}
    ticker_list = [_ticker(it) for it in items if _ticker(it)]
    n = len(ticker_list)
    if progress_callback and n > 0:
        progress_callback(f"銘柄スコア計算開始 ({n} 件): 株価・ファンダメンタル・Value/Safety/Momentum・β/ATR")

    for idx, item in enumerate(items):
        ticker = _ticker(item)
        if not ticker:
            continue
        if progress_callback and n > 0:
            progress_callback(f"  [{idx + 1}/{n}] {ticker} 分析中…")
        elif verbose:
            print(f"DVC: {ticker} ...", file=sys.stderr)
        try:
            out = run_dvc_for_ticker(
                ticker=ticker,
                benchmark_ticker=benchmark_ticker,
                years=years,
                sector_peers_path=sector_peers_path,
                llm_enabled=llm_enabled,
                llm_client=None,
                bench_df=bench_df,
                peers_data=peers_data,
            )
            results[ticker] = out
            out_path = str(Path(output_dir) / f"{ticker}.json")
            save_output_json(out, out_path)
            if progress_callback and n > 0:
                progress_callback(f"  [{idx + 1}/{n}] {ticker} 完了 (total_score={out.scores.total_score})")
        except (KeyError, TypeError, ValueError, OSError) as e:
            if progress_callback and n > 0:
                progress_callback(f"  [{idx + 1}/{n}] {ticker} スキップ: {e}")
            elif verbose:
                print(f"  skip {ticker}: {e}", file=sys.stderr)
        except Exception:
            raise

    # スコア履歴を更新（date キーには JST の「今日」を用いる）
    today_key = _now_jst().date().isoformat()
    update_scores_history_for_date(today_key, results, path=scores_history_path or SCORES_HISTORY_PATH)
    if progress_callback and n > 0:
        progress_callback(f"スコア履歴を更新しました ({today_key})")

    return results

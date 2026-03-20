"""
BFF (Backend For Frontend) API layer.
Merges last_report, previous_report, positions for report view.
Does not modify core/ — uses existing JSON and invokes core via subprocess/import only.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from fastapi import APIRouter, BackgroundTasks, HTTPException

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "config_example.yaml"
LAST_REPORT_PATH = DATA_DIR / "last_report.json"
PREVIOUS_REPORT_PATH = DATA_DIR / "previous_report.json"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"
PORTFOLIO_STATE_PATH = PROJECT_ROOT / "portfolio_state.json"
RUN_STATUS_PATH = DATA_DIR / "run_status.json"
DAILY_ROUTINE_SCRIPT = PROJECT_ROOT / "daily_routine.py"


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {} if "report" not in str(path) and "portfolio" not in str(path) else None
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_run_status(status: str, message: str, step: Optional[int] = None, total_steps: int = 7, finished_at: Optional[str] = None) -> None:
    from datetime import datetime
    payload = {
        "status": status,
        "message": message,
        "step": step,
        "total_steps": total_steps,
        "finished_at": finished_at,
    }
    _write_json(RUN_STATUS_PATH, payload)


def _get_cash_yen() -> float:
    """portfolio_state.json から現金残高を取得。"""
    state = _read_json(PORTFOLIO_STATE_PATH)
    if not isinstance(state, dict):
        return 0.0
    try:
        return float(state.get("cash_yen", 0))
    except (TypeError, ValueError):
        return 0.0


def _get_positions_from_watchlist() -> dict:
    """watchlist の HOLDING から positions 相当を返す。"""
    try:
        from core.utils.watchlist_io import positions_from_watchlist
        return positions_from_watchlist(path=str(WATCHLIST_PATH))
    except ImportError:
        return {}


def _merge_report_data() -> dict[str, Any]:
    """Load last_report, previous_report, positions and merge: unrealized_pnl, rank_change, price_change."""
    last = _read_json(LAST_REPORT_PATH)
    if not last:
        return {"report": None, "holdings_merged": [], "watchlist_merged": [], "purge": None, "draft": None}
    prev = _read_json(PREVIOUS_REPORT_PATH)
    positions = _get_positions_from_watchlist()

    last_prices = last.get("last_prices") or {}
    ticker_names = last.get("ticker_names") or {}
    current_weights = last.get("current_weights") or {}
    target_weights = last.get("target_weights") or {}
    score_trends = last.get("score_trends") or {}
    portfolio_scores = last.get("portfolio_scores") or {}

    prev_prices = (prev or {}).get("last_prices") or {}
    prev_scores = (prev or {}).get("portfolio_scores") or {}
    prev_score_trends = (prev or {}).get("score_trends") or {}
    prev_current_weights = (prev or {}).get("current_weights") or {}
    prev_target_weights = (prev or {}).get("target_weights") or {}

    # Ordered watchlist: by portfolio_scores desc, then target_weights
    tickers_ordered = sorted(
        set(portfolio_scores.keys()) | set(target_weights.keys()),
        key=lambda t: (float(portfolio_scores.get(t) or 0), float(target_weights.get(t) or 0)),
        reverse=True,
    )
    prev_ordered = sorted(
        set(prev_scores.keys()),
        key=lambda t: float(prev_scores.get(t) or 0),
        reverse=True,
    )
    rank_now = {t: i + 1 for i, t in enumerate(tickers_ordered)}
    rank_prev = {t: i + 1 for i, t in enumerate(prev_ordered)}

    def rank_change(t: str) -> str:
        if t not in rank_prev:
            return "flat"
        rn, rp = rank_now.get(t), rank_prev.get(t)
        if rn is None or rp is None:
            return "flat"
        if rn < rp:
            return "up"
        if rn > rp:
            return "down"
        return "flat"

    def price_change(t: str) -> Optional[float]:
        if t not in prev_prices or t not in last_prices:
            return None
        try:
            return float(last_prices[t]) - float(prev_prices[t])
        except (TypeError, ValueError):
            return None

    # ① Holdings with unrealized_pnl
    holdings_merged = []
    for ticker in list(current_weights.keys()):
        if float(current_weights.get(ticker) or 0) <= 0:
            continue
        pos = positions.get(ticker) or {}
        shares = pos.get("shares") or pos.get("shares_held") or 0
        try:
            shares = int(shares)
        except (TypeError, ValueError):
            shares = 0
        avg_price = pos.get("avg_price")
        try:
            avg_price = float(avg_price) if avg_price is not None else None
        except (TypeError, ValueError):
            avg_price = None
        current_price = last_prices.get(ticker)
        try:
            current_price = float(current_price) if current_price is not None else None
        except (TypeError, ValueError):
            current_price = None
        unrealized_pnl = None
        if current_price is not None and avg_price is not None and shares:
            unrealized_pnl = (current_price - avg_price) * shares
        st = score_trends.get(ticker) or {}
        prev_st = prev_score_trends.get(ticker) or {}
        try:
            prev_score = float(prev_st.get("last")) if prev_st.get("last") is not None else None
        except (TypeError, ValueError):
            prev_score = None
        try:
            prev_trend = float(prev_st.get("trend")) if prev_st.get("trend") is not None else None
        except (TypeError, ValueError):
            prev_trend = None
        prev_price = None
        if ticker in prev_prices:
            try:
                prev_price = float(prev_prices[ticker])
            except (TypeError, ValueError):
                pass
        prev_cw = prev_current_weights.get(ticker)
        prev_tw = prev_target_weights.get(ticker)
        holdings_merged.append({
            "ticker": ticker,
            "name": ticker_names.get(ticker) or "-",
            "current_weight": current_weights.get(ticker),
            "target_weight": target_weights.get(ticker),
            "score": st.get("last"),
            "trend": st.get("trend"),
            "level": st.get("level"),
            "price": current_price,
            "shares": shares,
            "avg_price": avg_price,
            "unrealized_pnl": unrealized_pnl,
            "prev_current_weight": float(prev_cw) if prev_cw is not None else None,
            "prev_target_weight": float(prev_tw) if prev_tw is not None else None,
            "prev_score": prev_score,
            "prev_trend": prev_trend,
            "prev_price": prev_price,
        })

    # ② Watchlist priority with rank_change, price_change, prev score/trend for color
    watchlist_merged = []
    for i, ticker in enumerate(tickers_ordered):
        st = score_trends.get(ticker) or {}
        prev_st = prev_score_trends.get(ticker) or {}
        try:
            prev_score = float(prev_st.get("last")) if prev_st.get("last") is not None else None
        except (TypeError, ValueError):
            prev_score = None
        try:
            prev_trend = float(prev_st.get("trend")) if prev_st.get("trend") is not None else None
        except (TypeError, ValueError):
            prev_trend = None
        cur_price = last_prices.get(ticker)
        watchlist_merged.append({
            "rank": i + 1,
            "ticker": ticker,
            "name": ticker_names.get(ticker) or "-",
            "status": "HOLDING" if float(current_weights.get(ticker) or 0) > 0 else "WATCHING",
            "score": st.get("last"),
            "trend": st.get("trend"),
            "level": st.get("level"),
            "price": float(cur_price) if cur_price is not None else None,
            "rank_change": rank_change(ticker),
            "price_change": price_change(ticker),
            "prev_score": prev_score,
            "prev_trend": prev_trend,
        })

    return {
        "report": last,
        "holdings_merged": holdings_merged,
        "watchlist_merged": watchlist_merged,
        "purge": last.get("purge"),
        "draft": last.get("draft"),
    }


def _run_batch_background() -> None:
    """Run daily_routine.py in subprocess; update run_status.json from stderr."""
    import threading
    from datetime import datetime

    def run():
        _write_run_status("running", "日次バッチを開始しています…", step=None)
        step_re = re.compile(r"\[\s*(\d+)\s*/\s*(\d+)\s*\]")
        env = {**__import__("os").environ, "PYTHONUNBUFFERED": "1"}
        try:
            proc = subprocess.Popen(
                [sys.executable, str(DAILY_ROUTINE_SCRIPT)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            for line in iter(proc.stdout.readline, "") if proc.stdout else []:
                line = (line or "").strip()
                m = step_re.search(line)
                if m:
                    step_num = int(m.group(1))
                    total = int(m.group(2))
                    _write_run_status("running", line or "処理中…", step=step_num, total_steps=total)
            proc.wait()
            finished_at = datetime.now().isoformat()
            if proc.returncode == 0:
                _write_run_status("completed", "日次バッチが完了しました。", step=7, total_steps=7, finished_at=finished_at)
            else:
                _write_run_status("failed", f"日次バッチが終了しました（コード: {proc.returncode}）", step=None, finished_at=finished_at)
        except Exception as e:
            _write_run_status("failed", str(e), finished_at=datetime.now().isoformat())

    t = threading.Thread(target=run, daemon=True)
    t.start()


router = APIRouter(prefix="/api", tags=["api"])


@router.get("/status")
def get_status() -> dict:
    """Batch run status (for polling)."""
    data = _read_json(RUN_STATUS_PATH)
    if data is None or not isinstance(data, dict):
        return {"status": "idle", "message": "", "step": None, "total_steps": 7, "finished_at": None}
    return {
        "status": data.get("status", "idle"),
        "message": data.get("message", ""),
        "step": data.get("step"),
        "total_steps": data.get("total_steps", 7),
        "finished_at": data.get("finished_at"),
    }


@router.post("/run_batch")
def run_batch(background_tasks: BackgroundTasks) -> dict:
    """Start daily batch in background."""
    status = _read_json(RUN_STATUS_PATH)
    if isinstance(status, dict) and status.get("status") == "running":
        raise HTTPException(status_code=409, detail="バッチは既に実行中です。")
    background_tasks.add_task(_run_batch_background)
    return {"ok": True, "message": "日次バッチを開始しました。"}


@router.post("/analyze")
def analyze_ticker(body: dict) -> dict:
    """Run DVC for one ticker and add to watchlist (using core)."""
    raw = (body.get("ticker") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="コードを指定してください。")
    # 英数字とドットのみ許可（例: 7203, AAPL, 7203.T）
    normalized = re.sub(r"[^A-Za-z0-9.]", "", raw)
    if not normalized or len(normalized) < 2 or len(normalized) > 20:
        raise HTTPException(status_code=400, detail="コードは 2〜20 文字の英数字で指定してください（例: 7203, AAPL）。")
    # 4桁数字のみの場合は日本株として .T を付与
    if re.fullmatch(r"[0-9]{4}", normalized):
        ticker = f"{normalized}.T"
    else:
        ticker = normalized
    try:
        from core.utils.config_loader import get_validated_config, load_config
        from core.utils.daily_cache import DEFAULT_CACHE_PATH, get_macro_and_peers_data
        from core.dvc.scoring import run_dvc_for_ticker
        from core.utils.watchlist_io import add_to_watchlist, load_watchlist, WATCHLIST_PATH
        from core.utils.io_utils import save_output_json
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"core の読み込みに失敗しました: {e}") from e
    cfg = get_validated_config(load_config(None, use_example_as_base=True))
    sector_peers_path = str(Path(cfg.get("sector_peers_path", "data/sector_peers.json")).resolve())
    if not Path(sector_peers_path).exists():
        raise HTTPException(status_code=500, detail="sector_peers.json が見つかりません。")
    try:
        bench_df, peers_data, _ = get_macro_and_peers_data(
            benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
            years=int(cfg.get("years", 5)),
            sector_peers_path=sector_peers_path,
            cache_path=str(Path(cfg.get("cache_path", DEFAULT_CACHE_PATH)).resolve()),
            vi_ticker=cfg.get("vi_ticker"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データ取得に失敗しました: {e}") from e
    try:
        result = run_dvc_for_ticker(
            ticker=ticker,
            benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
            years=int(cfg.get("years", 5)),
            sector_peers_path=sector_peers_path,
            llm_enabled=False,
            llm_client=None,
            bench_df=bench_df,
            peers_data=peers_data,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析に失敗しました: {e}") from e
    output_dir = Path(cfg.get("output_dir", "output")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_path = output_dir / f"{ticker}.json"
    save_output_json(result, str(saved_path))
    max_items = int(cfg.get("watchlist_max_items", 30))
    before_count = len(load_watchlist(str(WATCHLIST_PATH)))
    add_to_watchlist(ticker, path=str(WATCHLIST_PATH), scores_by_ticker={ticker: result}, max_items=max_items)
    after_count = len(load_watchlist(str(WATCHLIST_PATH)))
    evicted = before_count >= max_items and after_count == max_items
    scores = result.scores
    # 保存済みJSONから再読み込み（確実に全フィールド取得＋JSONシリアライズ可能な型）
    d = {}
    if saved_path.exists():
        try:
            d = json.loads(saved_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    s = d.get("scores") or {}
    ml = d.get("market_linkage") or {}
    rm = d.get("risk_metrics") or {}
    ao = d.get("data_overview") or {}
    fund = ao.get("fundamentals") or {}
    ph = ao.get("price_history") or {}
    vi = ao.get("value_inputs") or {}
    sp = ao.get("sector_peers") or {}
    last_close = ph.get("last_close")
    bps = fund.get("book_value_per_share")
    eps = fund.get("eps_ttm")
    pb = (float(last_close) / float(bps)) if (last_close is not None and bps and float(bps) > 0) else None
    pe = (float(last_close) / float(eps)) if (last_close is not None and eps and float(eps) > 0) else None
    last_report = _read_json(LAST_REPORT_PATH) or {}
    portfolio_scores = last_report.get("portfolio_scores") or {}
    wl = load_watchlist(str(WATCHLIST_PATH))
    wl_tickers = [it.get("ticker") or it.get("ticker_symbol", "") for it in wl if (it.get("ticker") or it.get("ticker_symbol"))]
    ticker_scores = {}
    for t in wl_tickers:
        if t == ticker:
            ticker_scores[t] = float(scores.total_score or 0)
        elif t in portfolio_scores:
            ticker_scores[t] = float(portfolio_scores[t])
        else:
            op_path = output_dir / f"{t}.json"
            if op_path.exists():
                try:
                    j = json.loads(op_path.read_text(encoding="utf-8"))
                    ticker_scores[t] = float((j.get("scores") or {}).get("total_score") or 0)
                except Exception:
                    ticker_scores[t] = 0.0
            else:
                ticker_scores[t] = 0.0
    sorted_tickers = sorted(ticker_scores.keys(), key=lambda t: -(ticker_scores.get(t) or 0))
    watchlist_rank = sorted_tickers.index(ticker) + 1 if ticker in sorted_tickers else 0
    return {
        "ok": True,
        "ticker": ticker,
        "name": d.get("name") or result.name,
        "sector": d.get("sector") or result.sector,
        "value_score": s.get("value_score"),
        "safety_score": s.get("safety_score"),
        "momentum_score": s.get("momentum_score"),
        "total_score": s.get("total_score"),
        "last_close": last_close,
        "beta": ml.get("beta"),
        "r_squared": ml.get("r_squared"),
        "alpha": ml.get("alpha"),
        "atr_percent": rm.get("atr_percent"),
        "stop_loss_recommendation": (d.get("ai_analysis") or {}).get("stop_loss_recommendation"),
        "pb": pb,
        "pe": pe,
        "bps": bps,
        "eps": eps,
        "date_min": ph.get("date_min"),
        "date_max": ph.get("date_max"),
        "rows": ph.get("rows"),
        "benchmark": ml.get("benchmark"),
        "peer_count": sp.get("peer_count"),
        "time_z_pb": vi.get("time_z_pb"),
        "time_z_pe": vi.get("time_z_pe"),
        "space_z_pb": vi.get("space_z_pb"),
        "space_z_pe": vi.get("space_z_pe"),
        "target_pb": vi.get("target_pb"),
        "target_pe": vi.get("target_pe"),
        "watchlist_rank": watchlist_rank,
        "watchlist_total": len(sorted_tickers),
        "message": "ウォッチリストに自動追加されました。" + ("（上限超過のため最下位をパージしました）" if evicted else ""),
    }


def _run_dvc_for_ticker(ticker: str) -> None:
    """銘柄の DVC を実行し output/<ticker>.json に保存。scores_history も更新。"""
    from core.utils.config_loader import get_validated_config, load_config
    from core.utils.daily_cache import DEFAULT_CACHE_PATH, get_macro_and_peers_data, _now_jst
    from core.dpa.dpa_scores import update_scores_history_for_date
    from core.dvc.scoring import run_dvc_for_ticker
    from core.utils.io_utils import save_output_json

    cfg = get_validated_config(load_config(None, use_example_as_base=True))
    sector_peers_path = str(Path(cfg.get("sector_peers_path", "data/sector_peers.json")).resolve())
    bench_df, peers_data, _ = get_macro_and_peers_data(
        benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
        years=int(cfg.get("years", 5)),
        sector_peers_path=sector_peers_path,
        cache_path=str(Path(cfg.get("cache_path", DEFAULT_CACHE_PATH)).resolve()),
        vi_ticker=cfg.get("vi_ticker"),
    )
    result = run_dvc_for_ticker(
        ticker=ticker,
        benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
        years=int(cfg.get("years", 5)),
        sector_peers_path=sector_peers_path,
        llm_enabled=False,
        llm_client=None,
        bench_df=bench_df,
        peers_data=peers_data,
    )
    output_dir = Path(cfg.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    save_output_json(result, str(output_dir / f"{ticker}.json"))
    scores_path = str(Path(cfg.get("scores_history_path", "data/scores_history.json")).resolve())
    today_key = _now_jst().date().isoformat()
    update_scores_history_for_date(today_key, {ticker: result}, path=scores_path)


@router.post("/trade/purchase")
def trade_purchase(body: dict) -> dict:
    """購入を記録。HOLDING 追加、現金から購入額を控除。"""
    raw = (body.get("ticker") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="コードを指定してください。")
    normalized = re.sub(r"[^A-Za-z0-9.]", "", raw)
    if not normalized or len(normalized) < 2 or len(normalized) > 20:
        raise HTTPException(status_code=400, detail="コードは 2〜20 文字の英数字で指定してください。")
    ticker = f"{normalized}.T" if re.fullmatch(r"[0-9]{4}", normalized) else normalized

    try:
        shares = int(body.get("shares", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="株数を指定してください。")
    if shares < 1:
        raise HTTPException(status_code=400, detail="株数は 1 以上で指定してください。")

    try:
        avg_price = float(body.get("avg_price", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="取得単価を指定してください。")
    if avg_price <= 0:
        raise HTTPException(status_code=400, detail="取得単価を正の数で指定してください。")

    cost = shares * avg_price
    state = _read_json(PORTFOLIO_STATE_PATH) or {}
    if not isinstance(state, dict):
        state = {}
    cash = float(state.get("cash_yen", 0))
    if cash < cost:
        raise HTTPException(status_code=400, detail=f"現金不足です。使える現金: {cash:,.0f} 円、購入額: {cost:,.0f} 円")

    wl = _read_json(WATCHLIST_PATH)
    if not isinstance(wl, list):
        wl = []
    existing_tickers = {x.get("ticker") or x.get("ticker_symbol") or "" for x in wl}
    if ticker not in existing_tickers:
        try:
            _run_dvc_for_ticker(ticker)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"{ticker} の企業分析に失敗しました: {e}") from e

    try:
        from core.utils.watchlist_io import update_holdings_bulk
        last_report = _read_json(LAST_REPORT_PATH) or {}
        portfolio_scores = last_report.get("portfolio_scores") or {}
        cfg = _load_config_raw()
        max_items = int((cfg.get("watchlist") or {}).get("max_items", 30))
        update_holdings_bulk(
            {ticker: {"shares": shares, "avg_price": avg_price}},
            path=str(WATCHLIST_PATH),
            portfolio_scores=portfolio_scores,
            max_items=max_items,
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"core の読み込みに失敗しました: {e}") from e

    state["cash_yen"] = cash - cost
    _write_json(PORTFOLIO_STATE_PATH, state)
    return {"ok": True, "cash_yen": state["cash_yen"]}


@router.post("/trade/sale")
def trade_sale(body: dict) -> dict:
    """売却を記録。HOLDING の株数を減らし（0 なら WATCHING に）、現金に売却代金を加算。"""
    ticker = (body.get("ticker") or "").strip()
    if not ticker:
        raise HTTPException(status_code=400, detail="銘柄を選択してください。")
    try:
        shares_to_sell = int(body.get("shares", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="売却株数を指定してください。")
    if shares_to_sell < 1:
        raise HTTPException(status_code=400, detail="売却株数は 1 以上で指定してください。")

    last_report = _read_json(LAST_REPORT_PATH) or {}
    last_prices = last_report.get("last_prices") or {}
    current_price = last_prices.get(ticker)
    try:
        price = float(current_price) if current_price is not None else 0.0
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        raise HTTPException(status_code=400, detail=f"{ticker} の株価データがありません。日次バッチを実行してから売却を記録してください。")

    wl = _read_json(WATCHLIST_PATH)
    if not isinstance(wl, list):
        raise HTTPException(status_code=400, detail="ウォッチリストの読み込みに失敗しました。")
    ticker_to_item = {x.get("ticker") or x.get("ticker_symbol") or "": x for x in wl}
    if ticker not in ticker_to_item:
        raise HTTPException(status_code=400, detail=f"{ticker} は保有銘柄にありません。")
    item = ticker_to_item[ticker]
    if (item.get("status") or "WATCHING") != "HOLDING":
        raise HTTPException(status_code=400, detail=f"{ticker} は保有銘柄ではありません。")
    current_shares = int(item.get("shares") or item.get("shares_held") or 0)
    if shares_to_sell > current_shares:
        raise HTTPException(status_code=400, detail=f"売却株数は保有株数（{current_shares}）以下で指定してください。")

    proceeds = shares_to_sell * price
    new_shares = current_shares - shares_to_sell

    for i in wl:
        if (i.get("ticker") or i.get("ticker_symbol")) == ticker:
            i["shares"] = new_shares
            if new_shares <= 0:
                i["status"] = "WATCHING"
                if "shares" in i:
                    del i["shares"]
            break
    _write_json(WATCHLIST_PATH, wl)

    state = _read_json(PORTFOLIO_STATE_PATH) or {}
    if not isinstance(state, dict):
        state = {}
    cash = float(state.get("cash_yen", 0))
    state["cash_yen"] = cash + proceeds
    _write_json(PORTFOLIO_STATE_PATH, state)
    return {"ok": True, "cash_yen": state["cash_yen"]}


CONFIG_KEYS = {
    "benchmark_ticker", "years", "output_dir", "llm_enabled",
    "vi_ticker", "mu_cash", "a_vi", "b_macd", "daily_report_email_enabled",
    "watchlist_max_items",
    # DPA 売却・購入（UI は % 表示、YAML は小数・円で保存）
    "over_weight_threshold_pct",
    "max_position_percent",
    "max_position_jpy",
    "ignition_momentum_threshold",
    "max_draft_candidates",
}


@router.post("/settings/update")
def update_settings(body: dict) -> dict:
    """Update portfolio_state.json (cash_yen) と config.yaml。"""
    result: dict = {}
    if "cash_yen" in body:
        try:
            cash_yen = float(body["cash_yen"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="cash_yen は数値で指定してください。")
        state = _read_json(PORTFOLIO_STATE_PATH) or {}
        if not isinstance(state, dict):
            state = {}
        state["cash_yen"] = cash_yen
        _write_json(PORTFOLIO_STATE_PATH, state)
        result["cash_yen"] = cash_yen
    flat = {k: v for k, v in body.items() if k in CONFIG_KEYS}
    if flat:
        cfg = _flat_to_config(flat)
        _save_config(cfg)
        result["config"] = _config_to_flat(cfg)
    if not result:
        raise HTTPException(status_code=400, detail="更新する項目を指定してください。")
    return {"ok": True, **result}


@router.get("/report/merged")
def get_report_merged() -> dict:
    """Merged report data for /report page (BFF)."""
    return _merge_report_data()


@router.get("/watchlist")
def get_watchlist() -> dict:
    """Watchlist and positions for UI."""
    wl = _read_json(WATCHLIST_PATH)
    if not isinstance(wl, list):
        wl = []
    pos = _get_positions_from_watchlist()
    return {"watchlist": wl, "positions": pos}


@router.delete("/watchlist/{ticker}")
def remove_watchlist_ticker(ticker: str) -> dict:
    """Remove ticker from watchlist (uses core)."""
    try:
        from core.utils.watchlist_io import remove_from_watchlist, WATCHLIST_PATH
    except ImportError:
        raise HTTPException(status_code=500, detail="core の読み込みに失敗しました。")
    remove_from_watchlist(ticker, path=str(WATCHLIST_PATH))
    return {"ok": True, "ticker": ticker}


def _load_config_raw() -> dict:
    """config.yaml を config_example とマージして返す。"""
    base: dict = {}
    if CONFIG_EXAMPLE_PATH.exists():
        try:
            base = yaml.safe_load(CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            base = {}
    if CONFIG_PATH.exists():
        try:
            override = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            _deep_merge(base, override)
        except Exception:
            pass
    return base


def _deep_merge(base: dict, override: dict) -> None:
    """base に override を再帰的にマージ（破壊的）。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _config_to_flat(cfg: dict) -> dict:
    """設定をフラット形式（UI用）に変換。YAML の null / 欠損でも常にスカラーで返す。"""
    dpa = cfg.get("dpa") or {}
    llm = cfg.get("llm") or {}
    email_cfg = cfg.get("daily_report") or {}
    wl_cfg = cfg.get("watchlist") or {}

    def _dpa_float(key: str, default: float) -> float:
        v = dpa.get(key)
        if v is None:
            return float(default)
        return float(v)

    def _dpa_int(key: str, default: int) -> int:
        v = dpa.get(key)
        if v is None:
            return int(default)
        return int(v)

    _ign = dpa.get("ignition_momentum_threshold")
    _mom = dpa.get("momentum_threshold")
    _ignite = float(_ign) if _ign is not None else (float(_mom) if _mom is not None else 50.0)

    bt = cfg.get("benchmark_ticker")
    if not bt:
        bt = "1306.T"
    yrs = cfg.get("years")
    if yrs is None:
        yrs = 5
    od = cfg.get("output_dir")
    if not od:
        od = "output"
    wl_max = wl_cfg.get("max_items")
    if wl_max is None:
        wl_max = 30

    ow = dpa.get("over_weight_threshold")
    if ow is None:
        ow = 0.02
    mp = dpa.get("max_position_pct")
    if mp is None:
        mp = 0.15

    _vi = dpa.get("vi_ticker")
    vi_ticker = "^VIX" if _vi is None else (str(_vi).strip() or "^VIX")

    return {
        "benchmark_ticker": str(bt).strip() or "1306.T",
        "years": int(yrs),
        "output_dir": str(od).strip() or "output",
        "llm_enabled": bool(llm.get("enabled", False)),
        "watchlist_max_items": int(wl_max),
        "vi_ticker": vi_ticker,
        "mu_cash": _dpa_float("mu_cash", 0.4),
        "a_vi": _dpa_float("a_vi", 0.2),
        "b_macd": _dpa_float("b_macd", 0.2),
        "daily_report_email_enabled": bool(email_cfg.get("enabled", True)),
        "over_weight_threshold_pct": round(float(ow) * 100.0, 4),
        "max_position_percent": round(float(mp) * 100.0, 4),
        "max_position_jpy": _dpa_float("max_position_jpy", 750_000.0),
        "ignition_momentum_threshold": _ignite,
        "max_draft_candidates": _dpa_int("max_draft_candidates", 5),
    }


def _flat_to_config(flat: dict) -> dict:
    """フラット形式を config のネスト形式に変換。"""
    cfg = _load_config_raw()
    if "benchmark_ticker" in flat:
        cfg["benchmark_ticker"] = str(flat["benchmark_ticker"]).strip()
    if "years" in flat:
        try:
            cfg["years"] = int(flat["years"])
        except (TypeError, ValueError):
            pass
    if "output_dir" in flat:
        cfg["output_dir"] = str(flat["output_dir"]).strip()
    if "watchlist_max_items" in flat:
        try:
            v = int(flat["watchlist_max_items"])
            if 5 <= v <= 100:
                cfg.setdefault("watchlist", {})["max_items"] = v
        except (TypeError, ValueError):
            pass
    if "llm_enabled" in flat:
        cfg.setdefault("llm", {})["enabled"] = bool(flat["llm_enabled"])
    dpa = cfg.setdefault("dpa", {})
    if "vi_ticker" in flat:
        v = str(flat["vi_ticker"]).strip()
        dpa["vi_ticker"] = v if v else "^VIX"
    if "mu_cash" in flat:
        try:
            dpa["mu_cash"] = float(flat["mu_cash"])
        except (TypeError, ValueError):
            pass
    if "a_vi" in flat:
        try:
            dpa["a_vi"] = float(flat["a_vi"])
        except (TypeError, ValueError):
            pass
    if "b_macd" in flat:
        try:
            dpa["b_macd"] = float(flat["b_macd"])
        except (TypeError, ValueError):
            pass
    if "daily_report_email_enabled" in flat:
        cfg.setdefault("daily_report", {})["enabled"] = bool(flat["daily_report_email_enabled"])
    if "over_weight_threshold_pct" in flat:
        try:
            v = float(flat["over_weight_threshold_pct"])
            if 0 < v <= 100:
                dpa["over_weight_threshold"] = v / 100.0
        except (TypeError, ValueError):
            pass
    if "max_position_percent" in flat:
        try:
            v = float(flat["max_position_percent"])
            if 0 < v <= 100:
                dpa["max_position_pct"] = v / 100.0
        except (TypeError, ValueError):
            pass
    if "max_position_jpy" in flat:
        try:
            v = float(flat["max_position_jpy"])
            if v > 0:
                dpa["max_position_jpy"] = v
        except (TypeError, ValueError):
            pass
    if "ignition_momentum_threshold" in flat:
        try:
            dpa["ignition_momentum_threshold"] = float(flat["ignition_momentum_threshold"])
        except (TypeError, ValueError):
            pass
    if "max_draft_candidates" in flat:
        try:
            v = int(flat["max_draft_candidates"])
            if 1 <= v <= 30:
                dpa["max_draft_candidates"] = v
        except (TypeError, ValueError):
            pass
    return cfg


def _save_config(cfg: dict) -> None:
    """config.yaml に保存。"""
    CONFIG_PATH.write_text(
        yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


@router.get("/settings")
def get_settings() -> dict:
    """Portfolio state と config を返す（設定画面用）。"""
    state = _read_json(PORTFOLIO_STATE_PATH)
    if not isinstance(state, dict):
        state = {}
    cfg = _config_to_flat(_load_config_raw())
    return {"cash_yen": state.get("cash_yen"), "config": cfg}

"""
BFF (Backend For Frontend) API layer.
Merges last_report, previous_report, positions for report view.
Does not modify core/ — uses existing JSON and invokes core via subprocess/import only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import copy
from pathlib import Path
from typing import Any, Optional

import yaml

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from core.utils.config_loader import (
    DEFAULT_WATCHLIST_MAX_ITEMS,
    load_merged_config,
    watchlist_max_items_from_raw_config,
)
from core.persistence import get_persistence
from core.utils.money import yen_floor

PROJECT_ROOT = Path(__file__).resolve().parent.parent
limiter = Limiter(key_func=get_remote_address)
RUN_BATCH_RATE_LIMIT = os.environ.get("DPA_RUN_BATCH_RATE", "3/minute")

DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
LAST_REPORT_PATH = DATA_DIR / "last_report.json"
PREVIOUS_REPORT_PATH = DATA_DIR / "previous_report.json"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"
PORTFOLIO_STATE_PATH = PROJECT_ROOT / "portfolio_state.json"
RUN_STATUS_PATH = DATA_DIR / "run_status.json"
DAILY_ROUTINE_SCRIPT = PROJECT_ROOT / "daily_routine.py"


DAILY_ROUTINE_SCRIPT = PROJECT_ROOT / "daily_routine.py"

_json_locks: dict[str, threading.Lock] = {}
_json_locks_guard = threading.Lock()
_batch_run_lock = threading.Lock()


def _lock_for_path(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _json_locks_guard:
        if key not in _json_locks:
            _json_locks[key] = threading.Lock()
        return _json_locks[key]


def _is_production() -> bool:
    return os.environ.get("DPA_ENV", "").lower() == "production"


def _server_error_detail(message: str) -> str:
    """本番 (DPA_ENV=production) では詳細を隠し、開発時のみ message を返す。"""
    if _is_production():
        return "内部エラーが発生しました。"
    return message


def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> None:
    """
    状態変更 API (POST/DELETE) 用の API キー認証。

    環境変数 ``DPA_API_KEY`` が**未設定**のときは開発モードとみなし、認証をスキップする。
    設定されている場合はリクエストヘッダ ``X-API-Key`` が一致しないと 401 を返す。
    """
    expected = os.environ.get("DPA_API_KEY")
    if not expected:
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="認証に失敗しました。")


def require_dpa_client_header(
    x_dpa_client: Optional[str] = Header(None, alias="X-DPA-Client"),
) -> None:
    """
    ブラウザ向け CSRF 対策。同一オリジンの UI からの POST/DELETE は ``X-DPA-Client: 1`` を付与する。
    """
    if x_dpa_client != "1":
        raise HTTPException(
            status_code=403,
            detail="この操作はアプリ画面からのみ実行できます。",
        )


MUTATING_DEPS = [Depends(require_api_key), Depends(require_dpa_client_header)]


def _normalize_ticker(raw: str) -> str:
    """銘柄コードを正規化（英数字・ドットのみ、4 桁数字は .T 付与）。"""
    normalized = re.sub(r"[^A-Za-z0-9.]", "", raw.strip())
    if not normalized or len(normalized) < 2 or len(normalized) > 20:
        raise HTTPException(
            status_code=400,
            detail="コードは 2〜20 文字の英数字で指定してください（例: 7203, AAPL）。",
        )
    if re.fullmatch(r"[0-9]{4}", normalized):
        return f"{normalized}.T"
    return normalized


def _resolve_output_dir(cfg: dict) -> Path:
    """output_dir を PROJECT_ROOT 配下に解決。それ以外は拒否。"""
    raw = str(cfg.get("output_dir") or "output").strip() or "output"
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="output_dir はプロジェクトルート配下を指定してください。",
        ) from exc
    return resolved


def _read_json(path: Path, default: Any = None) -> Any:
    if default is None:
        default = {} if "report" not in str(path) and "portfolio" not in str(path) else None
    path = path.resolve()
    lock = _lock_for_path(path)
    with lock:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default


def _write_json(path: Path, data: Any) -> None:
    path = path.resolve()
    lock = _lock_for_path(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _load_validated_config():
    """config.yaml を検証済み dict にして返す（API・バッチと同じ設定を使う）。"""
    from core.utils.config_loader import get_validated_config

    return get_validated_config(load_merged_config(None))


def _write_run_status(status: str, message: str, step: Optional[int] = None, total_steps: int = 7, finished_at: Optional[str] = None) -> None:
    get_persistence().run_job.update_status(
        status=status,
        message=message,
        step=step,
        total_steps=total_steps,
        finished_at=finished_at,
    )


def _get_cash_yen() -> int:
    """portfolio から現金残高を取得（整数円）。"""
    return get_persistence().portfolio.get_cash_yen()


def _get_positions_from_watchlist() -> dict:
    """watchlist の HOLDING から positions 相当を返す。"""
    return get_persistence().watchlist.get_positions()


def _compute_holdings_value(positions: dict, last_prices: dict) -> tuple[int, list[dict]]:
    """positions と last_prices から評価額と内訳を計算。"""
    total = 0.0
    detail: list[dict] = []
    for t, e in (positions or {}).items():
        try:
            shares = int((e.get("shares") if isinstance(e, dict) else None) or (e.get("shares_held") if isinstance(e, dict) else None) or 0)
        except (TypeError, ValueError):
            shares = 0
        if shares <= 0:
            continue
        price = last_prices.get(t)
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        avg = e.get("avg_price") if isinstance(e, dict) else None
        try:
            avg_f = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg_f = None
        value = (price_f * shares) if price_f is not None else 0.0
        total += value
        detail.append({
            "ticker": t,
            "shares": shares,
            "avg_price": avg_f,
            "last_price": price_f,
            "value": yen_floor(value) if price_f is not None else None,
        })
    return yen_floor(total), detail


def _record_portfolio_snapshot(source: str = "trade") -> dict[str, Any]:
    """現時点の総資産スナップショットを当日キーで upsert。"""
    from core.utils.dates import logical_date_iso

    store = get_persistence()
    positions = store.watchlist.get_positions()
    last_report = store.daily_report.get_last() or {}
    last_prices = last_report.get("last_prices") or {}
    equity_val, detail = _compute_holdings_value(positions, last_prices)
    cash = yen_floor(store.portfolio.get_cash_yen() or 0)
    total = yen_floor(cash + equity_val)
    snapshot = {
        "snapshot_date": logical_date_iso(),
        "cash_yen": cash,
        "equity_value_yen": equity_val,
        "total_capital_yen": total,
        "holdings": detail,
        "source": source,
    }
    return store.portfolio_snapshot.upsert(snapshot)


def _record_trade(
    side: str,
    ticker: str,
    shares: int,
    price: float,
    *,
    avg_price_before: Optional[float] = None,
    realized_pnl: Optional[float] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """取引履歴を1件追加。"""
    from core.utils.dates import logical_date_iso
    from datetime import datetime, timezone

    amount = yen_floor(shares * price)
    entry = {
        "trade_date": logical_date_iso(),
        "side": side.upper(),
        "ticker": ticker,
        "shares": int(shares),
        "price": float(price),
        "amount": amount,
        "avg_price_before": avg_price_before,
        "realized_pnl": realized_pnl,
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return get_persistence().trade_log.add(entry)


def _merge_report_data() -> dict[str, Any]:
    """Load last_report, previous_report, positions and merge: unrealized_pnl, rank_change, price_change."""
    reports = get_persistence().daily_report
    last = reports.get_last()
    if not last:
        return {"report": None, "holdings_merged": [], "watchlist_merged": [], "purge": None, "draft": None}
    prev = reports.get_previous()
    positions = _get_positions_from_watchlist()
    current_watchlist = get_persistence().watchlist.load_all()
    watchlist_tickers = {
        (
            item.get("ticker")
            if isinstance(item, dict)
            else getattr(item, "ticker", None)
        )
        or (
            item.get("ticker_symbol")
            if isinstance(item, dict)
            else getattr(item, "ticker_symbol", None)
        )
        for item in current_watchlist
    }
    watchlist_tickers = {t for t in watchlist_tickers if t}

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
        set(portfolio_scores.keys()) | set(target_weights.keys()) | watchlist_tickers,
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


class TradePurchaseBody(BaseModel):
    ticker: str
    shares: int = Field(ge=1)
    avg_price: float = Field(gt=0)


class TradeSaleBody(BaseModel):
    ticker: str
    shares: int = Field(ge=1)


class SettingsUpdateBody(BaseModel):
    """設定画面 POST /api/settings/update 用。未知キーは 422。"""

    model_config = ConfigDict(extra="forbid")

    cash_yen: Optional[float] = Field(None, ge=0)
    benchmark_ticker: Optional[str] = Field(None, min_length=1, max_length=40)
    years: Optional[int] = Field(None, ge=1, le=30)
    output_dir: Optional[str] = Field(None, min_length=1, max_length=200)
    llm_enabled: Optional[bool] = None
    vi_ticker: Optional[str] = Field(None, max_length=40)
    mu_cash: Optional[float] = Field(None, ge=0.0, le=1.0)
    a_vi: Optional[float] = Field(None, ge=0.0, le=2.0)
    b_macd: Optional[float] = Field(None, ge=0.0, le=2.0)
    daily_report_email_enabled: Optional[bool] = None
    watchlist_max_items: Optional[int] = Field(None, ge=5, le=100)
    purge_lot_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_position_percent: Optional[float] = Field(None, gt=0.0, le=100.0)
    max_position_jpy: Optional[float] = Field(None, gt=0.0)
    ignition_momentum_threshold: Optional[float] = Field(None, ge=0.0, le=100.0)
    max_draft_candidates: Optional[int] = Field(None, ge=1, le=30)


@router.get("/status")
def get_status() -> dict:
    """Batch run status (for polling)."""
    data = get_persistence().run_job.get_status()
    return {
        "status": data.get("status", "idle"),
        "message": data.get("message", ""),
        "step": data.get("step"),
        "total_steps": data.get("total_steps", 7),
        "finished_at": data.get("finished_at"),
    }


@router.post("/run_batch", dependencies=MUTATING_DEPS)
@limiter.limit(RUN_BATCH_RATE_LIMIT)
def run_batch(request: Request, background_tasks: BackgroundTasks) -> dict:
    """Start daily batch in background."""
    with _batch_run_lock:
        status = get_persistence().run_job.get_status()
        if status.get("status") == "running":
            raise HTTPException(status_code=409, detail="バッチは既に実行中です。")
        _write_run_status("running", "日次バッチを開始しています…", step=None)
        background_tasks.add_task(_run_batch_background)
    return {"ok": True, "message": "日次バッチを開始しました。"}


@router.post("/analyze", dependencies=MUTATING_DEPS)
def analyze_ticker(body: dict) -> dict:
    """Run DVC for one ticker and add to watchlist (using core)."""
    raw = (body.get("ticker") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="コードを指定してください。")
    ticker = _normalize_ticker(raw)
    try:
        from core.utils.daily_cache import get_macro_and_peers_data
        from core.dvc.scoring import run_dvc_for_ticker
        from core.utils.watchlist_io import add_to_watchlist
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"core の読み込みに失敗しました: {e}"),
        ) from e
    cfg = _load_validated_config()
    if not get_persistence().sector_peers.load():
        sp = Path(cfg.get("sector_peers_path", "data/sector_peers.json"))
        if not sp.exists():
            raise HTTPException(status_code=500, detail=_server_error_detail("sector_peers.json が見つかりません。"))
    try:
        bench_df, peers_data, _ = get_macro_and_peers_data(
            benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
            years=int(cfg.get("years", 5)),
            vi_ticker=cfg.get("vi_ticker"),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"データ取得に失敗しました: {e}"),
        ) from e
    try:
        result = run_dvc_for_ticker(
            ticker=ticker,
            benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
            years=int(cfg.get("years", 5)),
            llm_enabled=False,
            llm_client=None,
            bench_df=bench_df,
            peers_data=peers_data,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"分析に失敗しました: {e}"),
        ) from e
    output_dir = _resolve_output_dir(cfg)
    get_persistence().ticker_analysis.save(ticker, result.model_dump(mode="json"))
    max_items = int(cfg.get("watchlist_max_items", DEFAULT_WATCHLIST_MAX_ITEMS))
    _wl, was_added, did_evict_watching = add_to_watchlist(
        ticker,
        path=str(get_persistence().paths.watchlist_path),
        scores_by_ticker={ticker: result},
        max_items=max_items,
    )
    d = get_persistence().ticker_analysis.get(ticker) or {}
    if not d and result is not None:
        d = {"name": result.name, "sector": result.sector, "scores": result.scores.model_dump()}
    msg = (
        "すでにウォッチリストに登録されています。"
        if not was_added
        else (
            "ウォッチリストに自動追加されました。（上限超過のため最下位をパージしました）"
            if did_evict_watching
            else "ウォッチリストに自動追加されました。"
        )
    )
    return _build_analyze_api_payload(
        ticker,
        d,
        output_dir,
        message=msg,
        fallback_name=result.name if result else None,
        fallback_sector=result.sector if result else None,
    )


OHLC_MAX_BARS = 2500


def _dataframe_to_ohlc_bars(df) -> list[dict[str, Any]]:
    """日足 DataFrame を Lightweight Charts 用の昇順バー配列に変換。"""
    required = ("open", "high", "low", "close")
    for col in required:
        if col not in df.columns:
            return []
    bars: list[dict[str, Any]] = []
    for ts, row in df.iterrows():
        if hasattr(ts, "strftime"):
            time_key = ts.strftime("%Y-%m-%d")
        else:
            time_key = str(ts)[:10]
        try:
            bars.append(
                {
                    "time": time_key,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
        except (TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b["time"])
    return bars


def _total_score_from_ticker_analysis(ticker: str) -> float | None:
    d = get_persistence().ticker_analysis.get(ticker)
    if not d:
        return None
    try:
        return float((d.get("scores") or {}).get("total_score") or 0)
    except (TypeError, ValueError):
        return None


def _watchlist_rank_for_ticker(ticker: str, output_dir: Path) -> tuple[int, int]:
    """ウォッチリスト内の total_score 順位 (1-based) と件数。"""
    last_report = get_persistence().daily_report.get_last() or {}
    portfolio_scores = last_report.get("portfolio_scores") or {}
    wl = get_persistence().watchlist.load_all()
    wl_tickers = [
        it.get("ticker") or it.get("ticker_symbol", "")
        for it in wl
        if (it.get("ticker") or it.get("ticker_symbol"))
    ]
    ticker_scores: dict[str, float] = {}
    for t in wl_tickers:
        if t in portfolio_scores:
            ticker_scores[t] = float(portfolio_scores[t])
        else:
            score = _total_score_from_ticker_analysis(t)
            ticker_scores[t] = score if score is not None else 0.0
    sorted_tickers = sorted(ticker_scores.keys(), key=lambda x: -(ticker_scores.get(x) or 0))
    rank = sorted_tickers.index(ticker) + 1 if ticker in sorted_tickers else 0
    return rank, len(sorted_tickers)


def _build_analyze_api_payload(
    ticker: str,
    d: dict,
    output_dir: Path,
    *,
    message: str = "",
    fallback_name: Optional[str] = None,
    fallback_sector: Optional[str] = None,
) -> dict[str, Any]:
    """output JSON から analyze API レスポンスを組み立てる。"""
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
    watchlist_rank, watchlist_total = _watchlist_rank_for_ticker(ticker, output_dir)
    return {
        "ok": True,
        "ticker": ticker,
        "name": d.get("name") or fallback_name,
        "sector": d.get("sector") or fallback_sector,
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
        "watchlist_total": watchlist_total,
        "message": message,
        "has_output": True,
    }


def _run_dvc_for_ticker(ticker: str) -> None:
    """銘柄の DVC を実行し output/<ticker>.json に保存。scores_history も更新。"""
    from core.utils.daily_cache import get_macro_and_peers_data, _now_jst
    from core.dvc.scoring import run_dvc_for_ticker

    cfg = _load_validated_config()
    bench_df, peers_data, _ = get_macro_and_peers_data(
        benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
        years=int(cfg.get("years", 5)),
        vi_ticker=cfg.get("vi_ticker"),
    )
    result = run_dvc_for_ticker(
        ticker=ticker,
        benchmark_ticker=cfg.get("benchmark_ticker", "1306.T"),
        years=int(cfg.get("years", 5)),
        llm_enabled=False,
        llm_client=None,
        bench_df=bench_df,
        peers_data=peers_data,
    )
    output_dir = _resolve_output_dir(cfg)
    get_persistence().ticker_analysis.save(ticker, result.model_dump(mode="json"))
    today_key = _now_jst().date().isoformat()
    s = result.scores
    get_persistence().score_history.upsert_day(
        today_key,
        {
            ticker: {
                "total": s.total_score,
                "value": s.value_score,
                "safety": s.safety_score,
                "momentum": s.momentum_score,
            }
        },
    )


@router.post("/trade/purchase", dependencies=MUTATING_DEPS)
def trade_purchase(body: TradePurchaseBody) -> dict:
    """購入を記録。HOLDING 追加、現金から購入額を控除。"""
    ticker = _normalize_ticker(body.ticker)
    shares = body.shares
    avg_price = yen_floor(body.avg_price)

    store = get_persistence()
    cost = yen_floor(shares * avg_price)
    cash = store.portfolio.get_cash_yen()
    if cash < cost:
        raise HTTPException(status_code=400, detail=f"現金不足です。使える現金: {cash:,.0f} 円、購入額: {cost:,.0f} 円")

    wl = store.watchlist.load_all()
    existing_tickers = {x.get("ticker") or x.get("ticker_symbol") or "" for x in wl}
    if ticker not in existing_tickers:
        try:
            _run_dvc_for_ticker(ticker)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=_server_error_detail(f"{ticker} の企業分析に失敗しました: {e}"),
            ) from e

    # 追加購入時の元 avg_price を記録（加重平均前）
    prior_positions = store.watchlist.get_positions()
    prior_entry = prior_positions.get(ticker) or {}
    try:
        avg_price_before = float(prior_entry.get("avg_price")) if prior_entry.get("avg_price") is not None else None
    except (TypeError, ValueError):
        avg_price_before = None

    wl_snapshot = copy.deepcopy(store.watchlist.load_all())
    try:
        from core.utils.watchlist_io import update_holdings_bulk
        last_report = get_persistence().daily_report.get_last() or {}
        portfolio_scores = last_report.get("portfolio_scores") or {}
        cfg = _load_validated_config()
        max_items = int(cfg.get("watchlist_max_items", DEFAULT_WATCHLIST_MAX_ITEMS))
        update_holdings_bulk(
            {ticker: {"shares": shares, "avg_price": avg_price}},
            path=str(store.paths.watchlist_path),
            portfolio_scores=portfolio_scores,
            max_items=max_items,
        )
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"core の読み込みに失敗しました: {e}"),
        ) from e

    # watchlist 更新後に portfolio 書込が失敗した場合、watchlist をロールバックして不整合を防ぐ
    try:
        store.portfolio.set_cash_yen(cash - cost)
    except Exception as e:
        store.watchlist.save_all(wl_snapshot)
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"現金残高の更新に失敗しました: {e}"),
        ) from e

    try:
        _record_trade(
            side="BUY",
            ticker=ticker,
            shares=shares,
            price=avg_price,
            avg_price_before=avg_price_before,
        )
        _record_portfolio_snapshot(source="trade")
    except Exception as e:
        print(f"warn: 取引履歴/スナップショット記録に失敗: {e}", file=sys.stderr)

    return {"ok": True, "cash_yen": store.portfolio.get_cash_yen()}


@router.post("/trade/sale", dependencies=MUTATING_DEPS)
def trade_sale(body: TradeSaleBody) -> dict:
    """売却を記録。HOLDING の株数を減らし（0 なら WATCHING に）、現金に売却代金を加算。"""
    ticker = _normalize_ticker(body.ticker)
    shares_to_sell = body.shares

    last_report = get_persistence().daily_report.get_last() or {}
    last_prices = last_report.get("last_prices") or {}
    current_price = last_prices.get(ticker)
    try:
        price = float(current_price) if current_price is not None else 0.0
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        raise HTTPException(status_code=400, detail=f"{ticker} の株価データがありません。日次バッチを実行してから売却を記録してください。")

    store = get_persistence()
    wl = store.watchlist.load_all()
    ticker_to_item = {x.get("ticker") or x.get("ticker_symbol") or "": x for x in wl}
    if ticker not in ticker_to_item:
        raise HTTPException(status_code=400, detail=f"{ticker} は保有銘柄にありません。")
    item = ticker_to_item[ticker]
    if (item.get("status") or "WATCHING") != "HOLDING":
        raise HTTPException(status_code=400, detail=f"{ticker} は保有銘柄ではありません。")
    current_shares = int(item.get("shares") or item.get("shares_held") or 0)
    if shares_to_sell > current_shares:
        raise HTTPException(status_code=400, detail=f"売却株数は保有株数（{current_shares}）以下で指定してください。")

    proceeds = yen_floor(shares_to_sell * price)
    new_shares = current_shares - shares_to_sell

    avg_price_before: Optional[float] = None
    try:
        v = item.get("avg_price")
        avg_price_before = float(v) if v is not None else None
    except (TypeError, ValueError):
        avg_price_before = None
    realized_pnl: Optional[float] = None
    if avg_price_before is not None:
        realized_pnl = (price - avg_price_before) * shares_to_sell

    for i in wl:
        if (i.get("ticker") or i.get("ticker_symbol")) == ticker:
            i["shares"] = new_shares
            if new_shares <= 0:
                i["status"] = "WATCHING"
                if "shares" in i:
                    del i["shares"]
                if "avg_price" in i:
                    del i["avg_price"]
            break
    store.watchlist.save_all(wl)

    cash = store.portfolio.get_cash_yen()
    store.portfolio.set_cash_yen(cash + proceeds)

    try:
        _record_trade(
            side="SELL",
            ticker=ticker,
            shares=shares_to_sell,
            price=price,
            avg_price_before=avg_price_before,
            realized_pnl=realized_pnl,
        )
        _record_portfolio_snapshot(source="trade")
    except Exception as e:
        print(f"warn: 取引履歴/スナップショット記録に失敗: {e}", file=sys.stderr)

    return {"ok": True, "cash_yen": store.portfolio.get_cash_yen()}


CONFIG_KEYS = {
    "benchmark_ticker", "years", "output_dir", "llm_enabled",
    "vi_ticker", "mu_cash", "a_vi", "b_macd", "daily_report_email_enabled",
    "watchlist_max_items",
    # DPA 売却・購入（UI は % 表示、YAML は小数・円で保存）
    "purge_lot_threshold",
    "max_position_percent",
    "max_position_jpy",
    "ignition_momentum_threshold",
    "max_draft_candidates",
}


@router.post("/settings/update", dependencies=MUTATING_DEPS)
def update_settings(body: SettingsUpdateBody) -> dict:
    """Update portfolio_state.json (cash_yen) と config.yaml。"""
    payload = body.model_dump(exclude_none=True)
    result: dict = {}
    if "cash_yen" in payload:
        cash_yen = yen_floor(payload["cash_yen"])
        get_persistence().portfolio.set_cash_yen(cash_yen)
        result["cash_yen"] = cash_yen
    flat = {k: v for k, v in payload.items() if k in CONFIG_KEYS}
    if "output_dir" in flat:
        _resolve_output_dir({"output_dir": flat["output_dir"]})
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


@router.get("/reports/snapshots")
def reports_snapshots(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
) -> dict:
    """資産推移のスナップショット一覧（日次・取引時）。"""
    store = get_persistence()
    snapshots = store.portfolio_snapshot.list_all(from_date=from_date, to_date=to_date)
    return {"snapshots": snapshots}


def _resolve_period_range(granularity: str, period: Optional[str]) -> tuple[str, str, str]:
    """granularity と period 文字列から (label, from_date, to_date) を返す。"""
    import calendar
    from core.utils.dates import logical_date_iso

    today = logical_date_iso()
    if granularity == "year":
        label = (period or today[:4]).strip()
        if len(label) != 4 or not label.isdigit():
            raise HTTPException(status_code=400, detail="year は YYYY 形式で指定してください。")
        y = int(label)
        return label, f"{y:04d}-01-01", f"{y:04d}-12-31"
    label = (period or today[:7]).strip()
    if len(label) != 7 or label[4] != "-" or not label[:4].isdigit() or not label[5:].isdigit():
        raise HTTPException(status_code=400, detail="month は YYYY-MM 形式で指定してください。")
    y, m = int(label[:4]), int(label[5:])
    last_day = calendar.monthrange(y, m)[1]
    return label, f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{last_day:02d}"


def _holdings_from_snapshot(snapshot: Optional[dict], ticker_names: dict) -> tuple[list[dict], float, float, float]:
    """end_snapshot.holdings から保有 PnL を組み立て。なければ (空, 0, 0, 0)。"""
    items: list[dict] = []
    cost_total = 0.0
    value_total = 0.0
    if not snapshot or not isinstance(snapshot.get("holdings"), list):
        return items, 0.0, 0.0, 0.0
    for h in snapshot["holdings"]:
        if not isinstance(h, dict):
            continue
        try:
            shares = int(h.get("shares") or 0)
        except (TypeError, ValueError):
            shares = 0
        if shares <= 0:
            continue
        try:
            avg = float(h.get("avg_price")) if h.get("avg_price") is not None else None
        except (TypeError, ValueError):
            avg = None
        try:
            price = float(h.get("last_price")) if h.get("last_price") is not None else None
        except (TypeError, ValueError):
            price = None
        cost = (avg * shares) if avg is not None else None
        value = (price * shares) if price is not None else None
        unreal = (value - cost) if (cost is not None and value is not None) else None
        ret = (unreal / cost * 100.0) if (cost and cost > 0 and unreal is not None) else None
        if cost is not None:
            cost_total += cost
        if value is not None:
            value_total += value
        items.append({
            "ticker": h.get("ticker"),
            "name": ticker_names.get(h.get("ticker")) or "-",
            "shares": shares,
            "avg_price": avg,
            "last_price": price,
            "cost_basis": yen_floor(cost) if cost is not None else None,
            "market_value": yen_floor(value) if value is not None else None,
            "unrealized_pnl": yen_floor(unreal) if unreal is not None else None,
            "return_pct": ret,
        })
    items.sort(key=lambda x: (x.get("unrealized_pnl") if x.get("unrealized_pnl") is not None else -1e18), reverse=True)
    return items, cost_total, value_total, (value_total - cost_total)


@router.get("/reports/period")
def reports_period(
    granularity: str = Query("month", pattern="^(month|year)$"),
    period: Optional[str] = Query(None),
) -> dict:
    """指定した月（YYYY-MM）または年（YYYY）に絞った包括レポート。"""
    label, from_date, to_date = _resolve_period_range(granularity, period)
    store = get_persistence()
    snapshots = store.portfolio_snapshot.list_all(from_date=from_date, to_date=to_date)
    trades = store.trade_log.list_all(from_date=from_date, to_date=to_date)
    last_report = store.daily_report.get_last() or {}
    ticker_names = last_report.get("ticker_names") or {}

    # baseline = 期間直前の最終スナップショット（期間損益の計算に使う）
    all_snapshots = store.portfolio_snapshot.list_all(to_date=from_date)
    baseline = None
    for s in reversed(all_snapshots):
        d = str(s.get("snapshot_date") or "")
        if d and d < from_date:
            baseline = s
            break

    start_snapshot = snapshots[0] if snapshots else None
    end_snapshot = snapshots[-1] if snapshots else None

    if baseline is not None:
        period_start_total = baseline.get("total_capital_yen")
    else:
        period_start_total = start_snapshot.get("total_capital_yen") if start_snapshot else None
    period_end_total = end_snapshot.get("total_capital_yen") if end_snapshot else None

    period_return = None
    period_return_pct = None
    if period_start_total is not None and period_end_total is not None:
        try:
            period_return = float(period_end_total) - float(period_start_total)
            if float(period_start_total) > 0:
                period_return_pct = period_return / float(period_start_total) * 100.0
        except (TypeError, ValueError):
            pass

    totals = [s.get("total_capital_yen") for s in snapshots if s.get("total_capital_yen") is not None]
    max_total = max(totals) if totals else None
    min_total = min(totals) if totals else None

    # 取引集計
    sells = [t for t in trades if str(t.get("side") or "").upper() == "SELL"]
    buys = [t for t in trades if str(t.get("side") or "").upper() == "BUY"]
    realized_total = 0.0
    for t in sells:
        if t.get("realized_pnl") is not None:
            try:
                realized_total += float(t["realized_pnl"])
            except (TypeError, ValueError):
                pass

    # 銘柄別実現損益
    pnl_by_ticker_map: dict[str, dict] = {}
    for t in sells:
        if t.get("realized_pnl") is None:
            continue
        tk = str(t.get("ticker") or "")
        e = pnl_by_ticker_map.setdefault(tk, {"ticker": tk, "realized_pnl": 0.0, "trade_count": 0, "proceeds_yen": 0.0})
        try:
            e["realized_pnl"] += float(t.get("realized_pnl") or 0)
            e["proceeds_yen"] += float(t.get("amount") or 0)
        except (TypeError, ValueError):
            pass
        e["trade_count"] += 1
    pnl_by_ticker = sorted(pnl_by_ticker_map.values(), key=lambda x: x["realized_pnl"], reverse=True)
    for it in pnl_by_ticker:
        it["name"] = ticker_names.get(it["ticker"]) or "-"
        it["realized_pnl"] = yen_floor(it["realized_pnl"])
        it["proceeds_yen"] = yen_floor(it["proceeds_yen"])

    buy_amount = yen_floor(sum(float(t.get("amount") or 0) for t in buys))
    sell_amount = yen_floor(sum(float(t.get("amount") or 0) for t in sells))

    # 取引活動: 最も取引した銘柄
    activity_map: dict[str, dict] = {}
    for t in trades:
        tk = str(t.get("ticker") or "")
        e = activity_map.setdefault(tk, {"ticker": tk, "trade_count": 0, "buy_count": 0, "sell_count": 0, "total_amount": 0.0})
        e["trade_count"] += 1
        try:
            e["total_amount"] += float(t.get("amount") or 0)
        except (TypeError, ValueError):
            pass
        if str(t.get("side") or "").upper() == "BUY":
            e["buy_count"] += 1
        else:
            e["sell_count"] += 1
    most_traded = sorted(activity_map.values(), key=lambda x: (x["trade_count"], x["total_amount"]), reverse=True)[:5]
    for it in most_traded:
        it["name"] = ticker_names.get(it["ticker"]) or "-"
        it["total_amount"] = yen_floor(it["total_amount"])

    # 期末時点の保有 PnL（snapshot.holdings から復元）
    holdings_items, h_cost, h_value, h_unreal = _holdings_from_snapshot(end_snapshot, ticker_names)
    holdings_as_of = end_snapshot.get("snapshot_date") if end_snapshot and end_snapshot.get("holdings") else None

    return {
        "granularity": granularity,
        "period": label,
        "from_date": from_date,
        "to_date": to_date,
        "snapshots": snapshots,
        "baseline_snapshot": baseline,
        "start_snapshot": start_snapshot,
        "end_snapshot": end_snapshot,
        "period_start_total": int(period_start_total) if period_start_total is not None else None,
        "period_end_total": int(period_end_total) if period_end_total is not None else None,
        "period_return": yen_floor(period_return) if period_return is not None else None,
        "period_return_pct": period_return_pct,
        "max_total": int(max_total) if max_total is not None else None,
        "min_total": int(min_total) if min_total is not None else None,
        "realized_pnl": yen_floor(realized_total),
        "realized_pnl_by_ticker": pnl_by_ticker,
        "buy_amount_yen": buy_amount,
        "sell_amount_yen": sell_amount,
        "net_flow_yen": sell_amount - buy_amount,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "trade_count": len(trades),
        "most_traded": most_traded,
        "holdings": {
            "items": holdings_items,
            "total_cost_basis": yen_floor(h_cost),
            "total_market_value": yen_floor(h_value),
            "total_unrealized_pnl": yen_floor(h_unreal),
            "as_of_date": holdings_as_of,
        },
    }


@router.get("/reports/available-periods")
def reports_available_periods() -> dict:
    """データのある月・年の一覧（現在月/現在年を含む）。"""
    from core.utils.dates import logical_date_iso

    store = get_persistence()
    months: set[str] = set()
    years: set[str] = set()
    for s in store.portfolio_snapshot.list_all():
        d = str(s.get("snapshot_date") or "")
        if len(d) >= 7:
            months.add(d[:7])
            years.add(d[:4])
    for t in store.trade_log.list_all():
        d = str(t.get("trade_date") or "")
        if len(d) >= 7:
            months.add(d[:7])
            years.add(d[:4])
    today = logical_date_iso()
    months.add(today[:7])
    years.add(today[:4])
    return {
        "months": sorted(months, reverse=True),
        "years": sorted(years, reverse=True),
        "current_month": today[:7],
        "current_year": today[:4],
    }


@router.get("/reports/trades")
def reports_trades(
    ticker: Optional[str] = Query(None),
    side: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
) -> dict:
    """取引履歴（フィルタ可: 銘柄・売買・期間）。"""
    store = get_persistence()
    t = _normalize_ticker(ticker) if ticker else None
    trades = store.trade_log.list_all(ticker=t, side=side, from_date=from_date, to_date=to_date)
    names = (store.daily_report.get_last() or {}).get("ticker_names") or {}
    for tr in trades:
        tr["name"] = names.get(tr.get("ticker")) or "-"
    return {"trades": trades}


@router.get("/reports/realized-pnl")
def reports_realized_pnl(
    period: str = Query("month", pattern="^(month|year)$"),
) -> dict:
    """実現損益を月次/年次で集計。"""
    store = get_persistence()
    trades = store.trade_log.list_all(side="SELL")
    buckets: dict[str, dict[str, float]] = {}
    for t in trades:
        pnl = t.get("realized_pnl")
        if pnl is None:
            continue
        d = str(t.get("trade_date") or "")
        if len(d) < 7:
            continue
        key = d[:7] if period == "month" else d[:4]
        bucket = buckets.setdefault(key, {"realized_pnl": 0.0, "proceeds": 0.0, "trade_count": 0})
        bucket["realized_pnl"] += float(pnl)
        bucket["proceeds"] += float(t.get("amount") or 0)
        bucket["trade_count"] += 1
    rows = [
        {
            "period": k,
            "realized_pnl": yen_floor(v["realized_pnl"]),
            "proceeds_yen": yen_floor(v["proceeds"]),
            "trade_count": int(v["trade_count"]),
        }
        for k, v in sorted(buckets.items())
    ]
    total = yen_floor(sum(float(r["realized_pnl"]) for r in rows))
    return {"period": period, "rows": rows, "total_realized_pnl": total}


@router.get("/reports/holdings-pnl")
def reports_holdings_pnl() -> dict:
    """保有銘柄ごとの含み損益と概要。"""
    store = get_persistence()
    positions = store.watchlist.get_positions()
    last_report = store.daily_report.get_last() or {}
    last_prices = last_report.get("last_prices") or {}
    ticker_names = last_report.get("ticker_names") or {}
    items: list[dict[str, Any]] = []
    total_cost = 0.0
    total_value = 0.0
    for t, e in (positions or {}).items():
        try:
            shares = int(e.get("shares") or e.get("shares_held") or 0)
        except (TypeError, ValueError):
            shares = 0
        if shares <= 0:
            continue
        try:
            avg = float(e.get("avg_price")) if e.get("avg_price") is not None else None
        except (TypeError, ValueError):
            avg = None
        price = last_prices.get(t)
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        cost = (avg * shares) if avg is not None else None
        value = (price_f * shares) if price_f is not None else None
        unreal = (value - cost) if (cost is not None and value is not None) else None
        ret_pct = (unreal / cost * 100.0) if (cost and cost > 0 and unreal is not None) else None
        if cost is not None:
            total_cost += cost
        if value is not None:
            total_value += value
        items.append({
            "ticker": t,
            "name": ticker_names.get(t) or "-",
            "shares": shares,
            "avg_price": avg,
            "last_price": price_f,
            "cost_basis": yen_floor(cost) if cost is not None else None,
            "market_value": yen_floor(value) if value is not None else None,
            "unrealized_pnl": yen_floor(unreal) if unreal is not None else None,
            "return_pct": ret_pct,
        })
    items.sort(key=lambda x: (x.get("unrealized_pnl") if x.get("unrealized_pnl") is not None else -1e18), reverse=True)
    total_unreal = total_value - total_cost if total_cost else 0.0
    return {
        "items": items,
        "total_cost_basis": yen_floor(total_cost),
        "total_market_value": yen_floor(total_value),
        "total_unrealized_pnl": yen_floor(total_unreal),
    }


@router.get("/reports/summary")
def reports_summary() -> dict:
    """レポート概要: 最新スナップショット・累積実現損益・取引件数。"""
    store = get_persistence()
    latest = store.portfolio_snapshot.latest()
    trades = store.trade_log.list_all()
    realized = 0.0
    sell_count = 0
    buy_count = 0
    for t in trades:
        side = str(t.get("side") or "").upper()
        if side == "SELL":
            sell_count += 1
            if t.get("realized_pnl") is not None:
                try:
                    realized += float(t.get("realized_pnl") or 0.0)
                except (TypeError, ValueError):
                    pass
        elif side == "BUY":
            buy_count += 1
    return {
        "latest_snapshot": latest,
        "total_realized_pnl": yen_floor(realized),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "total_trades": len(trades),
    }


def build_watchlist_analysis_index() -> list[dict[str, Any]]:
    """
    企業分析タブ用のウォッチリスト一覧メタデータ。
    watchlist_io と同じパスで読み込む（/watchlist ページと整合）。
    """
    wl = get_persistence().watchlist.load_all()
    last_report = get_persistence().daily_report.get_last() or {}
    names = last_report.get("ticker_names") or {}
    last_prices = last_report.get("last_prices") or {}
    portfolio_scores = last_report.get("portfolio_scores") or {}
    try:
        cfg = _load_validated_config()
        output_dir = _resolve_output_dir(cfg)
    except Exception:
        output_dir = PROJECT_ROOT / "output"
    items: list[dict[str, Any]] = []
    for x in wl:
        t = (x.get("ticker") or x.get("ticker_symbol") or "").strip()
        if not t:
            continue
        total_score = portfolio_scores.get(t)
        name = names.get(t)
        analysis = get_persistence().ticker_analysis.get(t)
        if analysis:
            if total_score is None:
                total_score = (analysis.get("scores") or {}).get("total_score")
            if not name:
                name = analysis.get("name")
        items.append(
            {
                "ticker": t,
                "name": name or "-",
                "status": x.get("status") or "WATCHING",
                "total_score": total_score,
                "last_close": last_prices.get(t),
                "has_output": analysis is not None,
            }
        )
    return items


@router.get("/watchlist/analysis-index")
def watchlist_analysis_index() -> dict:
    """企業分析タブ用: ウォッチリスト銘柄の一覧メタデータ。"""
    return {"items": build_watchlist_analysis_index()}


@router.get("/ticker/{ticker}/analysis")
def get_ticker_analysis(ticker: str) -> dict:
    """保存済み output JSON から分析詳細を返す。"""
    normalized = _normalize_ticker(ticker)
    cfg = _load_validated_config()
    output_dir = _resolve_output_dir(cfg)
    d = get_persistence().ticker_analysis.get(normalized)
    if d is None:
        raise HTTPException(status_code=404, detail=f"{normalized} の分析結果がありません。")
    if not isinstance(d, dict):
        raise HTTPException(status_code=404, detail=f"{normalized} の分析結果がありません。")
    return _build_analyze_api_payload(
        normalized,
        d,
        output_dir,
        message="保存済みの分析結果を表示しています。",
    )


@router.get("/ticker/{ticker}/ohlc")
def get_ticker_ohlc(ticker: str, years: int = Query(1, ge=1, le=30)) -> dict:
    """日足 OHLCV（チャート用）。既定は直近 1 年分。"""
    normalized = _normalize_ticker(ticker)
    try:
        from core.dvc.data_fetcher import fetch_price_history
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"core の読み込みに失敗しました: {e}"),
        ) from e
    try:
        df = fetch_price_history(normalized, years)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=_server_error_detail(f"株価データの取得に失敗しました: {e}"),
        ) from e
    bars = _dataframe_to_ohlc_bars(df)
    if not bars:
        raise HTTPException(status_code=404, detail=f"{normalized} の株価データがありません。")
    if len(bars) > OHLC_MAX_BARS:
        bars = bars[-OHLC_MAX_BARS:]
    return {"ticker": normalized, "years": years, "bars": bars}


@router.get("/watchlist")
def get_watchlist_api() -> dict:
    """Watchlist and positions for UI."""
    store = get_persistence()
    return {"watchlist": store.watchlist.load_all(), "positions": store.watchlist.get_positions()}


@router.delete("/watchlist/{ticker}", dependencies=MUTATING_DEPS)
def remove_watchlist_ticker(ticker: str) -> dict:
    """Remove ticker from watchlist (uses core)."""
    try:
        from core.utils.watchlist_io import remove_from_watchlist
    except ImportError:
        raise HTTPException(status_code=500, detail=_server_error_detail("core の読み込みに失敗しました。"))
    normalized = _normalize_ticker(ticker)
    remove_from_watchlist(normalized, path=str(get_persistence().paths.watchlist_path))
    return {"ok": True, "ticker": normalized}


def _load_config_raw() -> dict:
    """config.yaml の内容を返す（設定画面の読み込み・保存用）。"""
    return load_merged_config(None)


def _ensure_nested_dict(cfg: dict, key: str) -> dict:
    """
    cfg[key] が dict でない（null・欠損・誤った型）のとき空 dict に置き換えて返す。
    setdefault だけだと key が存在して値が None のとき壊れるため。
    """
    v = cfg.get(key)
    if not isinstance(v, dict):
        v = {}
        cfg[key] = v
    return v


def _config_to_flat(cfg: dict) -> dict:
    """設定をフラット形式（UI用）に変換。YAML の null / 欠損でも常にスカラーで返す。"""
    dpa = cfg.get("dpa") or {}
    llm = cfg.get("llm") or {}
    email_cfg = cfg.get("daily_report") or {}
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
        "watchlist_max_items": watchlist_max_items_from_raw_config(cfg),
        "vi_ticker": vi_ticker,
        "mu_cash": _dpa_float("mu_cash", 0.4),
        "a_vi": _dpa_float("a_vi", 0.2),
        "b_macd": _dpa_float("b_macd", 0.2),
        "daily_report_email_enabled": bool(email_cfg.get("enabled", True)),
        "purge_lot_threshold": _dpa_float("purge_lot_threshold", 0.5),
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
                _ensure_nested_dict(cfg, "watchlist")["max_items"] = v
        except (TypeError, ValueError):
            pass
    if "llm_enabled" in flat:
        _ensure_nested_dict(cfg, "llm")["enabled"] = bool(flat["llm_enabled"])
    dpa = _ensure_nested_dict(cfg, "dpa")
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
        _ensure_nested_dict(cfg, "daily_report")["enabled"] = bool(flat["daily_report_email_enabled"])
    if "purge_lot_threshold" in flat:
        try:
            v = float(flat["purge_lot_threshold"])
            if 0 <= v <= 1:
                dpa["purge_lot_threshold"] = v
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
    cfg = _config_to_flat(_load_config_raw())
    return {"cash_yen": get_persistence().portfolio.get_cash_yen(), "config": cfg}

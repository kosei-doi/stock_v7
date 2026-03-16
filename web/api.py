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
POSITIONS_PATH = DATA_DIR / "positions.json"
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


def _merge_report_data() -> dict[str, Any]:
    """Load last_report, previous_report, positions and merge: unrealized_pnl, rank_change, price_change."""
    last = _read_json(LAST_REPORT_PATH)
    if not last:
        return {"report": None, "holdings_merged": [], "watchlist_merged": [], "purge": None, "draft": None}
    prev = _read_json(PREVIOUS_REPORT_PATH)
    positions = _read_json(POSITIONS_PATH) or {}

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
        raise HTTPException(status_code=400, detail="ticker を指定してください。")
    # 英数字とドットのみ許可（例: 7203, AAPL, 7203.T）
    normalized = re.sub(r"[^A-Za-z0-9.]", "", raw)
    if not normalized or len(normalized) < 2 or len(normalized) > 20:
        raise HTTPException(status_code=400, detail="ticker は 2〜20 文字の英数字で指定してください（例: 7203, AAPL）。")
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
    output_dir = Path(cfg.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    save_output_json(result, str(output_dir / f"{ticker}.json"))
    max_items = int(cfg.get("watchlist_max_items", 30))
    before_count = len(load_watchlist(WATCHLIST_PATH))
    add_to_watchlist(ticker, path=WATCHLIST_PATH, scores_by_ticker={ticker: result}, max_items=max_items)
    after_count = len(load_watchlist(WATCHLIST_PATH))
    evicted = before_count >= max_items and after_count == max_items
    scores = result.scores
    return {
        "ok": True,
        "ticker": ticker,
        "name": result.name,
        "value_score": scores.value_score,
        "safety_score": scores.safety_score,
        "momentum_score": scores.momentum_score,
        "total_score": scores.total_score,
        "message": "ウォッチリストに自動追加されました。" + ("（上限超過のため最下位をパージしました）" if evicted else ""),
    }


@router.post("/positions/update")
def update_positions(body: dict) -> dict:
    """Update positions.json with provided { ticker: { shares, avg_price? } }."""
    if not isinstance(body.get("positions"), dict):
        raise HTTPException(status_code=400, detail="positions オブジェクトを送信してください。")
    positions = {}
    for ticker, entry in body["positions"].items():
        if not isinstance(entry, dict):
            continue
        shares = entry.get("shares") or entry.get("shares_held")
        try:
            shares = int(shares) if shares is not None else 0
        except (TypeError, ValueError):
            shares = 0
        avg = entry.get("avg_price")
        try:
            avg = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg = None
        positions[ticker] = {"shares": shares}
        if avg is not None:
            positions[ticker]["avg_price"] = avg
    _write_json(POSITIONS_PATH, positions)
    return {"ok": True, "positions": positions}


CONFIG_KEYS = {
    "benchmark_ticker", "years", "output_dir", "llm_enabled",
    "vi_ticker", "mu_cash", "a_vi", "b_macd", "daily_report_email_enabled",
    "watchlist_max_items",
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
    pos = _read_json(POSITIONS_PATH) or {}
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
    """設定をフラット形式（UI用）に変換。"""
    dpa = cfg.get("dpa") or {}
    llm = cfg.get("llm") or {}
    email_cfg = cfg.get("daily_report") or {}
    wl_cfg = cfg.get("watchlist") or {}
    return {
        "benchmark_ticker": cfg.get("benchmark_ticker", "1306.T"),
        "years": int(cfg.get("years", 5)),
        "output_dir": cfg.get("output_dir", "output"),
        "llm_enabled": bool(llm.get("enabled", False)),
        "watchlist_max_items": int(wl_cfg.get("max_items", 30)),
        "vi_ticker": dpa.get("vi_ticker") or "^VIX",
        "mu_cash": float(dpa.get("mu_cash", 0.4)),
        "a_vi": float(dpa.get("a_vi", 0.2)),
        "b_macd": float(dpa.get("b_macd", 0.2)),
        "daily_report_email_enabled": bool(email_cfg.get("enabled", True)),
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

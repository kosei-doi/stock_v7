"""
設定ファイルの読み込みと型検証を一括で行う共通モジュール。
ユーザー指定の config のみ、または example + ユーザー上書きを選択できる。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

# デフォルト定数（設定に無い場合に使用）
DEFAULT_BENCHMARK_TICKER = "1306.T"
DEFAULT_YEARS = 5
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_CACHE_PATH = "data/daily_cache.json"
DEFAULT_SECTOR_PEERS_PATH = "data/sector_peers.json"
DEFAULT_PORTFOLIO_PATH = "portfolio_state.json"
DEFAULT_CACHE_CUTOFF_HOUR = 6
DEFAULT_CACHE_CUTOFF_MINUTE = 0
DEFAULT_MARKET_TZ = "Asia/Tokyo"
DEFAULT_TOTAL_CAPITAL_JPY = 5_000_000
DEFAULT_MU_CASH = 0.4
DEFAULT_A_VI = 0.1
DEFAULT_B_MACD = 0.1
DEFAULT_MACD_SCALE = 0.002
DEFAULT_MIN_CASH_RATIO = 0.2
DEFAULT_MAX_CASH_RATIO = 0.8
DEFAULT_MOMENTUM_THRESHOLD = 50.0
DEFAULT_LOT_SIZE = 100
DEFAULT_SCORES_HISTORY_PATH = "data/scores_history.json"
DEFAULT_WATCHLIST_MAX_ITEMS = 30


def _project_root() -> Path:
    """プロジェクトルート（daily_routine.py があるディレクトリ）を返す。"""
    return Path(__file__).resolve().parent.parent.parent


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_str(value: Any, default: str) -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def load_config(
    config_path: Optional[Path] = None,
    use_example_as_base: bool = True,
) -> dict[str, Any]:
    """
    設定を読み込んでマージする。
    - use_example_as_base=True: config_example.yaml をベースに、config_path で上書き。
      example はプロジェクトルート（本モジュールの親ディレクトリ）基準で探す。
    - config_path を指定したがファイルが存在しない場合は上書きされない（呼び出し側で警告推奨）。
    """
    base: dict[str, Any] = {}
    if use_example_as_base:
        example = _project_root() / "config_example.yaml"
        if example.exists():
            try:
                with example.open(encoding="utf-8") as f:
                    base = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError):
                base = {}
    if config_path and config_path.exists():
        try:
            with config_path.open(encoding="utf-8") as f:
                override = yaml.safe_load(f) or {}
            base.update(override)
        except (OSError, yaml.YAMLError):
            pass
    return base


def get_validated_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    生の設定 dict を型変換・デフォルト補完した dict で返す。
    返り値は benchmark_ticker, years, output_dir, cache_path, sector_peers_path,
    cache_cutoff_hour, cache_cutoff_minute, market_tz, llm_enabled, llm_model,
    total_capital_jpy, portfolio_path, scores_history_path, vi_ticker, mu_cash, a_vi, b_macd,
    macd_scale, min_cash_ratio, max_cash_ratio, momentum_threshold, lot_size などを含む。
    vi_ticker は空文字のとき None に正規化する。
    """
    out: dict[str, Any] = {}
    out["benchmark_ticker"] = _coerce_str(cfg.get("benchmark_ticker"), DEFAULT_BENCHMARK_TICKER)
    out["years"] = _coerce_int(cfg.get("years"), DEFAULT_YEARS)
    out["output_dir"] = _coerce_str(cfg.get("output_dir"), DEFAULT_OUTPUT_DIR)

    cache_cfg = cfg.get("cache") or {}
    dpa_cfg = cfg.get("dpa") or {}
    out["cache_path"] = _coerce_str(
        cache_cfg.get("cache_path") or dpa_cfg.get("cache_path"),
        DEFAULT_CACHE_PATH,
    )
    out["cache_cutoff_hour"] = _coerce_int(
        cache_cfg.get("cutoff_hour") or dpa_cfg.get("cutoff_hour"),
        DEFAULT_CACHE_CUTOFF_HOUR,
    )
    out["cache_cutoff_minute"] = _coerce_int(
        cache_cfg.get("cutoff_minute") or dpa_cfg.get("cutoff_minute"),
        DEFAULT_CACHE_CUTOFF_MINUTE,
    )
    out["market_tz"] = _coerce_str(
        cache_cfg.get("market_tz") or dpa_cfg.get("market_tz"),
        DEFAULT_MARKET_TZ,
    )

    llm_cfg = cfg.get("llm") or {}
    out["llm_enabled"] = bool(llm_cfg.get("enabled", False))
    out["llm_model"] = _coerce_str(llm_cfg.get("model"), "gpt-4.1-mini")

    wl_cfg = cfg.get("watchlist") or {}
    out["watchlist_max_items"] = _coerce_int(wl_cfg.get("max_items"), DEFAULT_WATCHLIST_MAX_ITEMS)

    out["total_capital_jpy"] = _coerce_float(dpa_cfg.get("total_capital_jpy"), DEFAULT_TOTAL_CAPITAL_JPY)
    out["portfolio_path"] = _coerce_str(dpa_cfg.get("portfolio_path"), DEFAULT_PORTFOLIO_PATH)
    out["sector_peers_path"] = _coerce_str(
        dpa_cfg.get("sector_peers_path") or cfg.get("sector_peers_path"),
        DEFAULT_SECTOR_PEERS_PATH,
    )
    out["scores_history_path"] = _coerce_str(
        dpa_cfg.get("scores_history_path") or cfg.get("scores_history_path"),
        DEFAULT_SCORES_HISTORY_PATH,
    )
    out["vi_ticker"] = dpa_cfg.get("vi_ticker") or cfg.get("vi_ticker")  # Optional[str]
    if out["vi_ticker"] is not None:
        out["vi_ticker"] = str(out["vi_ticker"]).strip() or None
    out["mu_cash"] = _coerce_float(dpa_cfg.get("mu_cash"), DEFAULT_MU_CASH)
    out["a_vi"] = _coerce_float(dpa_cfg.get("a_vi"), DEFAULT_A_VI)
    out["b_macd"] = _coerce_float(dpa_cfg.get("b_macd"), DEFAULT_B_MACD)
    out["macd_scale"] = _coerce_float(dpa_cfg.get("macd_scale"), DEFAULT_MACD_SCALE)
    out["min_cash_ratio"] = _coerce_float(dpa_cfg.get("min_cash_ratio"), DEFAULT_MIN_CASH_RATIO)
    out["max_cash_ratio"] = _coerce_float(dpa_cfg.get("max_cash_ratio"), DEFAULT_MAX_CASH_RATIO)
    out["momentum_threshold"] = _coerce_float(dpa_cfg.get("momentum_threshold"), DEFAULT_MOMENTUM_THRESHOLD)
    out["lot_size"] = _coerce_int(dpa_cfg.get("lot_size"), DEFAULT_LOT_SIZE)

    return out

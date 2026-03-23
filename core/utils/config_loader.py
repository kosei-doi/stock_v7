"""
設定ファイルの読み込みと型検証を一括で行う共通モジュール。
プロジェクト直下の config.yaml（単一ファイル）を読む。欠損キーは get_validated_config で補完する。
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
DEFAULT_PURGE_LOT_THRESHOLD = 0.5
DEFAULT_MAX_POSITION_PCT = 0.15
DEFAULT_MAX_POSITION_JPY = 750_000.0
DEFAULT_MAX_DRAFT_CANDIDATES = 5
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


def watchlist_max_items_from_raw_config(cfg: dict[str, Any]) -> int:
    """
    YAML の生 dict からウォッチリスト登録上限を読む。
    - 標準: watchlist.max_items
    - 補助: トップレベル watchlist_max_items（誤ったインデントや旧形式の救済）
    watchlist が dict でない（null / リスト等）ときはネスト値は使わない。
    """
    wl_raw = cfg.get("watchlist")
    v: Any = None
    if isinstance(wl_raw, dict):
        v = wl_raw.get("max_items")
    if v is None:
        v = cfg.get("watchlist_max_items")
    return _coerce_int(v, DEFAULT_WATCHLIST_MAX_ITEMS)


def _coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def project_config_path() -> Path:
    """プロジェクトルートのユーザー設定ファイル（config.yaml）。"""
    return _project_root() / "config.yaml"


def load_merged_config(config_path: Optional[Path] = None) -> dict[str, Any]:
    """
    単一 YAML の内容を返す。
    - config_path が None: プロジェクト直下の config.yaml（存在すれば）。
    - 指定あり: そのファイル（CLI の --config 向け）。
    """
    if config_path is None:
        return load_config(None, default_to_project_yaml=True)
    return load_config(config_path, default_to_project_yaml=True)


def _coerce_str(value: Any, default: str) -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def load_config(
    config_path: Optional[Path] = None,
    default_to_project_yaml: bool = True,
) -> dict[str, Any]:
    """
    単一の YAML ファイルを読み込む。
    - config_path が None かつ default_to_project_yaml が True: プロジェクトの config.yaml があれば読む。
    - config_path が None かつ default_to_project_yaml が False: 空 dict。
    - config_path が指定されている: そのパス（存在しなければ空 dict）。default_to_project_yaml は無視される。
    """
    if config_path is None:
        if not default_to_project_yaml:
            return {}
        p = project_config_path()
        config_path = p if p.exists() else None
    if not config_path or not config_path.exists():
        return {}
    try:
        with config_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def get_validated_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    生の設定 dict を型変換・デフォルト補完した dict で返す。
    返り値は benchmark_ticker, years, output_dir, cache_path, sector_peers_path,
    cache_cutoff_hour, cache_cutoff_minute, market_tz, llm_enabled, llm_model,
    total_capital_jpy, portfolio_path, scores_history_path, vi_ticker, mu_cash, a_vi, b_macd,
    macd_scale, min_cash_ratio, max_cash_ratio, momentum_threshold, lot_size,
    purge_lot_threshold, max_position_pct, max_position_jpy,
    max_draft_candidates などを含む。
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

    out["watchlist_max_items"] = watchlist_max_items_from_raw_config(cfg)

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
    _ign = dpa_cfg.get("ignition_momentum_threshold")
    _mom = dpa_cfg.get("momentum_threshold")
    if _ign is not None:
        out["momentum_threshold"] = _coerce_float(_ign, DEFAULT_MOMENTUM_THRESHOLD)
    elif _mom is not None:
        out["momentum_threshold"] = _coerce_float(_mom, DEFAULT_MOMENTUM_THRESHOLD)
    else:
        out["momentum_threshold"] = DEFAULT_MOMENTUM_THRESHOLD
    out["lot_size"] = _coerce_int(dpa_cfg.get("lot_size"), DEFAULT_LOT_SIZE)
    out["purge_lot_threshold"] = _coerce_float(
        dpa_cfg.get("purge_lot_threshold"), DEFAULT_PURGE_LOT_THRESHOLD
    )
    out["max_position_pct"] = _coerce_float(dpa_cfg.get("max_position_pct"), DEFAULT_MAX_POSITION_PCT)
    out["max_position_jpy"] = _coerce_float(dpa_cfg.get("max_position_jpy"), DEFAULT_MAX_POSITION_JPY)
    out["max_draft_candidates"] = _coerce_int(
        dpa_cfg.get("max_draft_candidates"), DEFAULT_MAX_DRAFT_CANDIDATES
    )

    return out

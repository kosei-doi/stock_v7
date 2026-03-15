"""
日次キャッシュ機構: マクロ指標（ベンチマーク）と代表銘柄データを
daily_cache.json に保存し、同日中は yfinance をスキップする。

更新の実行可否は「日付が変わったか」だけでなく、時刻・曜日も考慮する:
- 週末: 新規データは出ないので、前週金曜日付きのキャッシュがあれば fresh とみなす。
- 平日の市場終了前: その日の終値はまだ出ていないので、直近営業日付きのキャッシュで十分。
- 平日の朝 6:00 JST 以降: 日本株・VIX など前日終値が揃った後とみなし、キャッシュは「今日」更新分のみ fresh。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import yfinance as yf

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

DEFAULT_CACHE_PATH = "data/daily_cache.json"
DEFAULT_CACHE_CUTOFF_HOUR = 6   # 日本時間 6:00 以降を境に「今日」のデータを要求（VIX 確定後）
DEFAULT_CACHE_CUTOFF_MINUTE = 0
DEFAULT_MARKET_TZ = "Asia/Tokyo"


def _today_iso() -> str:
    """JST の「今日」の ISO 日付文字列（キャッシュ・スコア履歴の日付キーと揃える）。"""
    return _now_jst().date().isoformat()


def _now_jst() -> datetime:
    """現在時刻を JST で返す（zoneinfo が無い場合はローカル時刻をそのまま）。"""
    if ZoneInfo is not None:
        return datetime.now(ZoneInfo(DEFAULT_MARKET_TZ))
    return datetime.now()


def _last_business_date_iso(d: date) -> date:
    """指定日において「直近の営業日」の日付を返す（土日は前週金曜）。"""
    w = d.weekday()  # 0=Mon, 6=Sun
    if w == 0:  # Monday
        return d - timedelta(days=3)  # Friday
    if w >= 5:  # Saturday=5, Sunday=6
        return d - timedelta(days=w - 4)  # Sat->Fri, Sun->Fri
    return d - timedelta(days=1)  # Tue–Fri -> yesterday


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def _is_after_cutoff(now: datetime, hour: int, minute: int) -> bool:
    """now が指定した時刻以降か（同日比較）。"""
    return (now.hour, now.minute) >= (hour, minute)


def cache_is_fresh(
    cache: dict | None,
    *,
    benchmark_ticker: str,
    years: int,
    vi_ticker: Optional[str] = None,
    now: Optional[datetime] = None,
    cutoff_hour: int = DEFAULT_CACHE_CUTOFF_HOUR,
    cutoff_minute: int = DEFAULT_CACHE_CUTOFF_MINUTE,
    market_tz: str = DEFAULT_MARKET_TZ,
) -> bool:
    """キャッシュが「今の時刻・曜日」の観点で fresh かどうか。

    - benchmark_ticker / years / vi_ticker が一致することは従来通り必須。
    - now を渡さない場合は従来どおり「updated_date が今日」なら fresh。
    - now を渡すとスケジュール考慮:
      - 週末: キャッシュの updated_date が直近金曜以降なら fresh（再取得しない）。
      - 平日のカットオフ前: updated_date が直近営業日以降なら fresh。
      - 平日のカットオフ後: updated_date が今日なら fresh（その日の終値取得済みとみなす）。
    """
    if cache is None:
        return False
    if cache.get("benchmark_ticker") != benchmark_ticker:
        return False
    if cache.get("years") != years:
        return False
    if vi_ticker is not None:
        if cache.get("vi_ticker") != vi_ticker:
            return False
        if "vi_history" not in cache:
            return False

    updated_str = cache.get("updated_date")
    if not updated_str:
        return False

    if now is None:
        return updated_str == _today_iso()

    try:
        updated_date_val = date.fromisoformat(updated_str)
    except (TypeError, ValueError):
        return False

    today = now.date() if hasattr(now, "date") else now
    last_biz = _last_business_date_iso(today)

    if _is_weekend(today):
        # 週末は新データが出ないので、金曜（以降）のキャッシュがあれば fresh
        return updated_date_val >= last_biz
    if _is_after_cutoff(now, cutoff_hour, cutoff_minute):
        # 平日・カットオフ後: その日の終値取得を期待 → 今日更新分のみ fresh
        return updated_date_val == today
    # 平日・カットオフ前: 直近営業日付きのキャッシュで十分
    return updated_date_val >= last_biz


def load_cache(path: str) -> dict | None:
    """daily_cache.json を読み込む。存在しないか不正な場合は None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _dataframe_to_cache(df: pd.DataFrame) -> dict:
    """DataFrame を JSON 保存用の dict に変換（orient=split, 日付は ISO 文字列）。"""
    if df is None or df.empty:
        return {"columns": [], "index": [], "data": []}
    df = df.copy()
    # 列が MultiIndex の場合は先頭レベルだけにし、下流で 'close' 等で参照できるようにする
    if hasattr(df.columns, "get_level_values"):
        df.columns = [
            c[0] if isinstance(c, (tuple, list)) and len(c) > 0 else c
            for c in df.columns
        ]
    df.index = df.index.astype(str)
    return json.loads(df.to_json(orient="split", date_format="iso"))


def _dataframe_from_cache(obj: dict) -> pd.DataFrame:
    """キャッシュ用 dict から DataFrame を復元。"""
    if not obj or not obj.get("data"):
        return pd.DataFrame()
    import io

    df = pd.read_json(io.StringIO(json.dumps(obj)), orient="split")
    if not df.empty and hasattr(df.index, "astype"):
        try:
            df.index = pd.to_datetime(df.index)
        except (ValueError, TypeError):
            pass
    # yfinance は単一銘柄でも MultiIndex 列を返すため、復元後は先頭レベルだけに平坦化
    if hasattr(df.columns, "get_level_values"):
        df.columns = [
            c[0] if isinstance(c, (tuple, list)) and len(c) > 0 else c
            for c in df.columns
        ]
    return df


def _fetch_peers_info(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """代表銘柄の currentPrice, bookValue, trailingEps を一括取得。"""
    if not tickers:
        return {}
    tickers_str = " ".join(tickers)
    peers_data = yf.Tickers(tickers_str)
    result: dict[str, dict[str, Any]] = {}
    for code in tickers:
        info = (peers_data.tickers.get(code) or yf.Ticker(code)).info or {}
        result[code] = {
            "currentPrice": info.get("currentPrice"),
            "bookValue": info.get("bookValue"),
            "trailingEps": info.get("trailingEps"),
        }
    return result


def _all_peer_tickers_from_map(peers_map: dict) -> list[str]:
    """sector_peers.json の全セクターから重複なしでティッカー一覧を取得。"""
    seen: set[str] = set()
    out: list[str] = []
    for tickers in peers_map.values():
        for t in tickers:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def fetch_and_save_cache(
    benchmark_ticker: str,
    years: int,
    peers_tickers: list[str],
    cache_path: str,
    vi_ticker: Optional[str] = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], Optional[pd.Series]]:
    """
    yfinance でベンチマーク履歴・代表銘柄情報・VI（任意）を取得し、
    daily_cache.json を上書き保存して (bench_df, peers_data, vi_series) を返す。
    VI は過去一定期間の終値系列ごとキャッシュし、後段でZスコア等を計算できるようにする。
    """
    from core.dvc.data_fetcher import fetch_price_history

    bench_df = fetch_price_history(benchmark_ticker, years)
    peers_data = _fetch_peers_info(peers_tickers)

    vi_series: Optional[pd.Series] = None
    vi_history_cache: Optional[dict[str, Any]] = None
    if vi_ticker and vi_ticker.strip():
        vi_df = yf.download(
            vi_ticker.strip(),
            period="120d",
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
        if not vi_df.empty:
            if "Close" in vi_df.columns and "close" not in vi_df.columns:
                vi_df = vi_df.rename(columns={"Close": "close"})
            vi_history_cache = _dataframe_to_cache(vi_df)
            s = vi_df["close"] if "close" in vi_df.columns else vi_df.iloc[:, 0]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            vi_series = s.dropna().copy()

    # ベンチマークが空（取得失敗など）のときはキャッシュを上書きしない。次回 fresh 判定で再取得される。
    if bench_df is not None and not bench_df.empty:
        cache = {
            "updated_date": _today_iso(),
            "benchmark_ticker": benchmark_ticker,
            "years": years,
            "benchmark_history": _dataframe_to_cache(bench_df),
            "peers_data": peers_data,
            "vi_ticker": vi_ticker,
            "vi_history": vi_history_cache,
        }
        try:
            Path(cache_path).write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            raise OSError(f"キャッシュの書き込みに失敗しました: {cache_path}: {e}") from e
    return bench_df, peers_data, vi_series


def get_macro_and_peers_data(
    benchmark_ticker: str,
    years: int,
    sector_peers_path: str,
    cache_path: str = DEFAULT_CACHE_PATH,
    vi_ticker: Optional[str] = None,
    now: Optional[datetime] = None,
    cutoff_hour: int = DEFAULT_CACHE_CUTOFF_HOUR,
    cutoff_minute: int = DEFAULT_CACHE_CUTOFF_MINUTE,
    market_tz: str = DEFAULT_MARKET_TZ,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], Optional[pd.Series]]:
    """
    フローチャート通り:
    - キャッシュが fresh ならキャッシュから読込（yfinance スキップ）。
    - そうでなければ yfinance で取得しキャッシュを上書き。

    fresh の判定:
    - now を渡さない場合: 従来どおり「updated_date が今日」なら fresh。
    - now を渡す場合: 曜日・時刻を考慮（週末は金曜キャッシュで十分、平日はカットオフ後のみ「今日」を要求）。
    返り値は (bench_df, peers_data, vi_series)。vi_ticker を指定すると VI も取得・キャッシュする。
    """
    from core.dvc.data_fetcher import fetch_sector_peers_map

    peers_map = fetch_sector_peers_map(sector_peers_path)
    all_tickers = _all_peer_tickers_from_map(peers_map)
    cache = load_cache(cache_path)

    if cache_is_fresh(
        cache,
        benchmark_ticker=benchmark_ticker,
        years=years,
        vi_ticker=vi_ticker,
        now=now,
        cutoff_hour=cutoff_hour,
        cutoff_minute=cutoff_minute,
        market_tz=market_tz,
    ):
        if progress_callback:
            progress_callback("ベンチマーク・VI・代表銘柄: キャッシュから読込")
        bench_df = _dataframe_from_cache(cache.get("benchmark_history") or {})
        peers_data = cache.get("peers_data") or {}
        vi_history_obj = cache.get("vi_history") or {}
        vi_df = _dataframe_from_cache(vi_history_obj) if vi_history_obj else pd.DataFrame()
        vi_series: Optional[pd.Series] = None
        if not vi_df.empty:
            s = vi_df["close"] if "close" in vi_df.columns else vi_df.iloc[:, 0]
            if isinstance(s, pd.DataFrame):
                s = s.iloc[:, 0]
            vi_series = s.dropna().copy()
        return bench_df, peers_data, vi_series

    if progress_callback:
        progress_callback("ベンチマーク・VI・代表銘柄: APIで取得中…")
    out = fetch_and_save_cache(
        benchmark_ticker=benchmark_ticker,
        years=years,
        peers_tickers=all_tickers,
        cache_path=cache_path,
        vi_ticker=vi_ticker,
    )
    if progress_callback:
        progress_callback("ベンチマーク・VI・代表銘柄: 取得完了")
    return out

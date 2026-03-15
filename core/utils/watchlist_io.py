"""
ウォッチリストと保有ポジションの永続化（Single Source of Truth）。
上限30件、HOLDING は削除対象外の自動淘汰ルールを実装する。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TypedDict

from core.dvc.schema import DvcScoreOutput

WATCHLIST_PATH = "data/watchlist.json"
POSITIONS_PATH = "data/positions.json"
MAX_WATCHLIST = 30
STATUS_HOLDING = "HOLDING"
STATUS_WATCHING = "WATCHING"


class WatchlistItem(TypedDict, total=False):
    """ウォッチリスト1件。ticker は必須、status は省略時 WATCHING。"""
    ticker: str
    ticker_symbol: str  # ticker の別名（互換用）
    status: str


class PositionEntry(TypedDict, total=False):
    """銘柄ごとのポジション。shares または shares_held を参照する。"""
    shares: int
    shares_held: int
    avg_price: float


def load_watchlist(path: str = WATCHLIST_PATH) -> list[WatchlistItem]:
    """watchlist.json を読み込む。"""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_watchlist(items: list[WatchlistItem], path: str = WATCHLIST_PATH) -> None:
    """watchlist.json に保存する。"""
    p = Path(path)
    try:
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise OSError(f"ウォッチリストの書き込みに失敗しました: {p}: {e}") from e


def load_positions(path: str = POSITIONS_PATH) -> dict[str, PositionEntry]:
    """positions.json を読み込む。{ ticker: PositionEntry }。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {x.get("ticker", x.get("ticker_symbol", "")): x for x in data if x.get("ticker") or x.get("ticker_symbol")}
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_positions(positions: dict[str, PositionEntry], path: str = POSITIONS_PATH) -> None:
    """positions.json に保存する。"""
    p = Path(path)
    try:
        p.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        raise OSError(f"ポジションの書き込みに失敗しました: {p}: {e}") from e


def _ticker(item: WatchlistItem | dict) -> str:
    return (item.get("ticker") or item.get("ticker_symbol") or "").strip()


def add_to_watchlist(
    ticker: str,
    status: str = STATUS_WATCHING,
    path: str = WATCHLIST_PATH,
    scores_by_ticker: Optional[dict[str, DvcScoreOutput]] = None,
    portfolio_scores: Optional[dict[str, float]] = None,
) -> list[WatchlistItem]:
    """
    銘柄をウォッチリストに追加する。上限超過時はスコア最下位の WATCHING を削除。
    HOLDING は削除対象外。portfolio_scores があればそれで並べ（DPA と整合）、なければ total_score を使用。
    """
    items = load_watchlist(path)
    tickers = [_ticker(x) for x in items]
    if ticker in tickers:
        return items
    items.append({"ticker": ticker, "status": status})
    return _evict_if_over(items, path, scores_by_ticker=scores_by_ticker, portfolio_scores=portfolio_scores)


def _evict_if_over(
    items: list[WatchlistItem],
    path: str,
    scores_by_ticker: Optional[dict[str, DvcScoreOutput]] = None,
    portfolio_scores: Optional[dict[str, float]] = None,
) -> list[WatchlistItem]:
    """上限超過時、WATCHING のうちスコア最下位を削除。HOLDING は保護。portfolio_scores 優先で DPA と整合。"""
    if len(items) <= MAX_WATCHLIST:
        save_watchlist(items, path)
        return items
    # WATCHING のみ削除候補
    candidates = [i for i in items if (i.get("status") or STATUS_WATCHING) == STATUS_WATCHING]
    if not candidates:
        save_watchlist(items, path)
        return items
    def score_of(it: WatchlistItem | dict) -> float:
        t = _ticker(it)
        if portfolio_scores is not None and t in portfolio_scores:
            return float(portfolio_scores[t])
        if scores_by_ticker and t in scores_by_ticker:
            s = scores_by_ticker[t].scores.total_score
            return float(s) if s is not None else -1.0
        return -1.0
    candidates.sort(key=score_of)
    to_remove = candidates[0]
    ticker_remove = _ticker(to_remove)
    new_items = [i for i in items if _ticker(i) != ticker_remove]
    save_watchlist(new_items, path)
    return new_items


def remove_from_watchlist(ticker: str, path: str = WATCHLIST_PATH) -> list[WatchlistItem]:
    """銘柄をウォッチリストから削除する。HOLDING でも削除可能（呼び出し側で注意）。"""
    items = load_watchlist(path)
    new_items = [i for i in items if _ticker(i) != ticker]
    save_watchlist(new_items, path)
    return new_items


def set_status(ticker: str, status: str, path: str = WATCHLIST_PATH) -> list[WatchlistItem]:
    """銘柄のステータスを HOLDING / WATCHING に更新する。"""
    items = load_watchlist(path)
    for i in items:
        if _ticker(i) == ticker:
            i["status"] = status
            break
    save_watchlist(items, path)
    return items


def get_holdings(watchlist: Optional[list[WatchlistItem]] = None, path: str = WATCHLIST_PATH) -> list[WatchlistItem]:
    """ウォッチリストのうち HOLDING の銘柄一覧を返す。"""
    items = watchlist if watchlist is not None else load_watchlist(path)
    return [i for i in items if (i.get("status") or STATUS_WATCHING) == STATUS_HOLDING]


def get_watching(watchlist: Optional[list[WatchlistItem]] = None, path: str = WATCHLIST_PATH) -> list[WatchlistItem]:
    """ウォッチリストのうち WATCHING の銘柄一覧を返す。"""
    items = watchlist if watchlist is not None else load_watchlist(path)
    return [i for i in items if (i.get("status") or STATUS_WATCHING) == STATUS_WATCHING]

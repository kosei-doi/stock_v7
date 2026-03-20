"""
ウォッチリストと保有ポジションの永続化（Single Source of Truth）。
positions.json を廃止し、watchlist.json に統合。HOLDING 銘柄には shares / avg_price を持つ。
上限30件、HOLDING は削除対象外の自動淘汰ルールを実装する。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, TypedDict

from core.dvc.schema import DvcScoreOutput

WATCHLIST_PATH = "data/watchlist.json"
MAX_WATCHLIST = 30
STATUS_HOLDING = "HOLDING"
STATUS_WATCHING = "WATCHING"


class WatchlistItem(TypedDict, total=False):
    """ウォッチリスト1件。ticker は必須、status は省略時 WATCHING。HOLDING 時は shares を推奨。"""
    ticker: str
    ticker_symbol: str  # ticker の別名（互換用）
    status: str
    shares: int
    shares_held: int  # shares の別名（互換用）
    avg_price: float


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


def positions_from_watchlist(
    watchlist: Optional[list[WatchlistItem]] = None,
    path: str = WATCHLIST_PATH,
) -> dict[str, PositionEntry]:
    """
    watchlist の HOLDING 銘柄から positions 相当の dict を構築。
    { ticker: { shares, avg_price? } }。
    """
    items = watchlist if watchlist is not None else load_watchlist(path)
    out: dict[str, PositionEntry] = {}
    for i in items:
        if (i.get("status") or STATUS_WATCHING) != STATUS_HOLDING:
            continue
        t = _ticker(i)
        if not t:
            continue
        shares = i.get("shares") or i.get("shares_held") or 0
        try:
            shares = int(shares)
        except (TypeError, ValueError):
            shares = 0
        entry: PositionEntry = {"shares": shares}
        avg = i.get("avg_price")
        if avg is not None:
            try:
                entry["avg_price"] = float(avg)
            except (TypeError, ValueError):
                pass
        out[t] = entry
    return out


def _ticker(item: WatchlistItem | dict) -> str:
    return (item.get("ticker") or item.get("ticker_symbol") or "").strip()


def add_to_watchlist(
    ticker: str,
    status: str = STATUS_WATCHING,
    path: str = WATCHLIST_PATH,
    shares: Optional[int] = None,
    avg_price: Optional[float] = None,
    scores_by_ticker: Optional[dict[str, DvcScoreOutput]] = None,
    portfolio_scores: Optional[dict[str, float]] = None,
    max_items: Optional[int] = None,
) -> list[WatchlistItem]:
    """
    銘柄をウォッチリストに追加する。上限超過時はスコア最下位の WATCHING を削除。
    HOLDING は削除対象外。portfolio_scores があればそれで並べ（DPA と整合）、なければ total_score を使用。
    status=HOLDING のときは shares（必須）、avg_price（任意）を渡せる。
    """
    items = load_watchlist(path)
    tickers = [_ticker(x) for x in items]
    if ticker in tickers:
        return items
    entry: WatchlistItem = {"ticker": ticker, "status": status}
    if status == STATUS_HOLDING and shares is not None:
        entry["shares"] = int(shares)
        if avg_price is not None:
            entry["avg_price"] = float(avg_price)
    items.append(entry)
    return _evict_if_over(
        items, path,
        scores_by_ticker=scores_by_ticker,
        portfolio_scores=portfolio_scores,
        max_items=max_items or MAX_WATCHLIST,
    )


def add_or_update_holding(
    ticker: str,
    shares: int = 0,
    avg_price: Optional[float] = None,
    path: str = WATCHLIST_PATH,
) -> tuple[list[WatchlistItem], bool]:
    """
    銘柄を HOLDING として追加または更新する。既存なら shares/avg_price を更新。
    戻り値: (更新後の watchlist, 新規追加したかどうか)
    """
    items = load_watchlist(path)
    for i in items:
        if _ticker(i) == ticker:
            i["status"] = STATUS_HOLDING
            i["shares"] = int(shares)
            if "shares_held" in i:
                del i["shares_held"]
            if avg_price is not None:
                i["avg_price"] = float(avg_price)
            elif "avg_price" in i:
                del i["avg_price"]
            save_watchlist(items, path)
            return items, False
    # 新規追加
    entry: WatchlistItem = {"ticker": ticker, "status": STATUS_HOLDING, "shares": int(shares)}
    if avg_price is not None:
        entry["avg_price"] = float(avg_price)
    items.append(entry)
    save_watchlist(items, path)
    return items, True


def update_holdings_bulk(
    positions: dict[str, dict],
    path: str = WATCHLIST_PATH,
    portfolio_scores: Optional[dict[str, float]] = None,
    max_items: Optional[int] = None,
) -> list[WatchlistItem]:
    """
    複数銘柄の shares / avg_price を一括更新。positions は { ticker: { shares, avg_price? } }。
    既存の HOLDING を更新し、positions に含まれるが watchlist にない銘柄は HOLDING で追加する。
    上限超過時は WATCHING のうちスコア最下位を自動削除（portfolio_scores で順序判定）。
    """
    items = load_watchlist(path)
    ticker_to_idx = {_ticker(x): idx for idx, x in enumerate(items)}
    for ticker, entry in positions.items():
        if not ticker or not isinstance(entry, dict):
            continue
        shares = entry.get("shares") or entry.get("shares_held")
        try:
            shares = int(shares) if shares is not None else 0
        except (TypeError, ValueError):
            shares = 0
        avg = entry.get("avg_price")
        try:
            avg_price = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg_price = None
        if ticker in ticker_to_idx:
            i = items[ticker_to_idx[ticker]]
            i["status"] = STATUS_HOLDING
            i["shares"] = shares
            if "shares_held" in i:
                del i["shares_held"]
            if avg_price is not None:
                i["avg_price"] = avg_price
            elif "avg_price" in i:
                del i["avg_price"]
        else:
            items.append({
                "ticker": ticker,
                "status": STATUS_HOLDING,
                "shares": shares,
                **({"avg_price": avg_price} if avg_price is not None else {}),
            })
    max_items = max_items if max_items is not None else MAX_WATCHLIST
    if len(items) > max_items:
        while len(items) > max_items:
            items = _evict_if_over(items, path, portfolio_scores=portfolio_scores, max_items=max_items)
    else:
        save_watchlist(items, path)
    return items


def _evict_if_over(
    items: list[WatchlistItem],
    path: str,
    scores_by_ticker: Optional[dict[str, DvcScoreOutput]] = None,
    portfolio_scores: Optional[dict[str, float]] = None,
    max_items: int = MAX_WATCHLIST,
) -> list[WatchlistItem]:
    """上限超過時、WATCHING のうちスコア最下位を削除。HOLDING は保護。portfolio_scores 優先で DPA と整合。"""
    if len(items) <= max_items:
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

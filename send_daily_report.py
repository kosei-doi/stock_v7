#!/usr/bin/env python3
"""
DPA 日次レポートを Gmail で自分宛てに送信するスクリプト。
初回実行時は credentials.json を読み込み、ブラウザで OAuth 認証後に token.json を保存する。
"""

import base64
import json
import os
import sys
import webbrowser
from email.mime.text import MIMEText
from typing import Optional
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# プロジェクトルートをカレントにする（credentials.json / token.json / data/ の位置）
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# 送信に加え、自分宛てアドレス取得のためプロフィール参照に readonly が必要
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"
DATA_DIR = ROOT / "data"


def load_credentials():
    """credentials.json と token.json で Gmail API 用の Credentials を取得。初回はブラウザで OAuth。"""
    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except ValueError as e:
            if "refresh_token" in str(e).lower() or "expected format" in str(e).lower():
                print("token.json が無効です（refresh_token なし）。再認証のためブラウザを開きます。", file=sys.stderr)
                creds = None  # 削除せず次で上書きする
            else:
                raise
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"credentials.json が見つかりません: {CREDENTIALS_FILE}", file=sys.stderr)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            try:
                # prompt='consent' で refresh_token を確実に取得（2回目以降ブラウザが開かなくなる）
                creds = flow.run_local_server(port=8080, prompt="consent")
            except webbrowser.Error:
                print("", file=sys.stderr)
                print("Cannot open browser on this machine (VPS/cron).", file=sys.stderr)
                print("On your Mac: run  python send_daily_report.py  then copy  token.json  to this server.", file=sys.stderr)
                print("Path on server: " + str(ROOT), file=sys.stderr)
                sys.exit(1)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def load_json(path: Path, default=None):
    """JSON ファイルを読み込む。存在しなければ default を返す。"""
    if default is None:
        default = {}
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _esc(s: str) -> str:
    """HTML エスケープ。"""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _diff(cur: Optional[float], prev: Optional[float]) -> int:
    """前日比: 増=1(赤), 減=-1(緑), 同様・不明=0."""
    if cur is None or prev is None:
        return 0
    try:
        c, p = float(cur), float(prev)
        if c > p:
            return 1
        if c < p:
            return -1
    except (TypeError, ValueError):
        pass
    return 0


def _table(headers: list[str], rows: list[list[str]], change_matrix: Optional[list[list[int]]] = None) -> str:
    """HTML テーブルを生成。change_matrix[i][j]: 1=増(赤文字), -1=減(緑文字), 0=色なし。枠線は常にグレー。"""
    h = "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" style=\"border-collapse:collapse; font-size:14px; border-color:#ccc;\">"
    h += "<thead><tr>" + "".join(f"<th style=\"background:#e0e0e0; border-color:#ccc;\">{_esc(x)}</th>" for x in headers) + "</tr></thead><tbody>"
    for ri, row in enumerate(rows):
        cells = []
        for i, x in enumerate(row):
            style = " border-color:#ccc;"
            if change_matrix and ri < len(change_matrix) and i < len(change_matrix[ri]):
                d = change_matrix[ri][i]
                if d == 1:
                    style += " color:#c62828;"   # 増＝赤文字
                elif d == -1:
                    style += " color:#2e7d32;"   # 減＝緑文字
            cells.append(f"<td style=\"{style}\">{_esc(str(x))}</td>")
        h += "<tr>" + "".join(cells) + "</tr>"
    h += "</tbody></table>"
    return h


def _kv_table(items: list[tuple[str, str]]) -> str:
    """項目・値の2列テーブル（背景色なし）。"""
    h = "<table cellpadding=\"8\" cellspacing=\"0\" style=\"border-collapse:collapse; font-size:14px;\">"
    for label, value in items:
        h += f"<tr><td style=\"font-weight:bold; width:180px;\">{_esc(label)}</td><td>{_esc(value)}</td></tr>"
    h += "</table>"
    return h


def _score_num(report: dict, ticker: str) -> Optional[float]:
    """レポートから銘柄のスコア数値を取得。"""
    st = (report.get("score_trends") or {}).get(ticker) or {}
    v = st.get("last")
    if v is not None:
        return float(v)
    v = (report.get("portfolio_scores") or {}).get(ticker)
    return float(v) if v is not None else None


def build_report_html() -> str:
    """
    アプリと同じ内容を HTML メールで送る。保有銘柄・ウォッチリストは表で表示。
    前日比で増＝赤・減＝緑で色付け（previous_report.json がある場合）。
    """
    run_status = load_json(DATA_DIR / "run_status.json", {})
    last_report = load_json(DATA_DIR / "last_report.json", {})
    previous_report = load_json(DATA_DIR / "previous_report.json", {})
    watchlist = load_json(DATA_DIR / "watchlist.json", [])
    portfolio = load_json(ROOT / "portfolio_state.json", {})

    ticker_names = last_report.get("ticker_names") or {}
    last_prices = last_report.get("last_prices") or {}
    current_weights = last_report.get("current_weights") or {}
    target_weights = last_report.get("target_weights") or {}
    score_trends = last_report.get("score_trends") or {}
    portfolio_scores = last_report.get("portfolio_scores") or {}

    prev_current_weights = previous_report.get("current_weights") or {}
    prev_target_weights = previous_report.get("target_weights") or {}
    prev_last_prices = previous_report.get("last_prices") or {}

    status_by_ticker = {w["ticker"]: w.get("status", "WATCHING") for w in watchlist if isinstance(w, dict)}

    def score_str(ticker: str) -> str:
        s = score_trends.get(ticker) or {}
        v = s.get("last")
        return f"{v:.1f}" if v is not None else (str(portfolio_scores.get(ticker, "-")) if portfolio_scores.get(ticker) is not None else "-")

    data_date = last_report.get("data_date", "")
    cash = last_report.get("cash_yen") if last_report.get("cash_yen") is not None else portfolio.get("cash_yen")
    total = last_report.get("total_capital_yen")
    equity = last_report.get("equity_value_yen")
    draft = last_report.get("draft") or {}
    raw_budget = draft.get("raw_available_budget")
    avail_budget = draft.get("available_budget")

    html_parts = [
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body style=\"font-family: sans-serif; max-width: 720px;\">",
        "<h2 style=\"margin-bottom: 0.5em;\">DPA 日次レポート</h2>",
        "",
        "<p style=\"margin-bottom: 0.3em; font-weight: bold;\">本日の目標現金比率: " + str(int((last_report.get("target_cash_ratio") or 0) * 100)) + "%</p>",
        "",
        _kv_table([
            ("マクロフェーズ", last_report.get("phase_name_ja") or last_report.get("phase") or "-"),
            ("VI Zスコア", str(last_report.get("vi_z", "-"))),
            ("MACDトレンド", str(last_report.get("macd_trend", "-"))),
        ]),
        "",
        "<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">ポートフォリオ概要</h3>",
        _kv_table([
            ("総資産", f"{total:,.0f} 円" if total is not None else "-"),
            ("現金", f"{cash:,.0f} 円" if cash is not None else "-"),
            ("株式評価額", f"{equity:,.0f} 円" if equity is not None else "-"),
            ("本日新規購入に使える理論上の最大額", f"{raw_budget:,.0f} 円" if raw_budget is not None else "-"),
            ("マクロ防衛モードにより実際の新規購入枠", f"{avail_budget:,.0f} 円" if avail_budget is not None else "-"),
        ]),
        "",
    ]

    purge = last_report.get("purge") or {}
    purge_items = purge.get("items") or []
    html_parts.append("<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">売却指示</h3>")
    if not purge_items:
        html_parts.append("<p>（なし）</p>")
    else:
        html_parts.append(_table(["銘柄", "理由"], [[_esc(str(x.get("ticker", ""))), _esc(str(x.get("reason", "")))] for x in purge_items]))
    html_parts.append("")

    html_parts.append("<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">保有銘柄の状況</h3>")
    if current_weights:
        hold_headers = ["銘柄", "名前", "現在%", "目標%", "スコア", "株価(円)"]
        hold_rows = []
        hold_changes = []
        for ticker in sorted(current_weights.keys(), key=lambda t: -(current_weights.get(t) or 0)):
            cw = (current_weights.get(ticker) or 0) * 100
            tw = (target_weights.get(ticker) or 0) * 100
            name = (ticker_names.get(ticker) or ticker)[:36]
            price = last_prices.get(ticker)
            prev_cw = (prev_current_weights.get(ticker) or 0) * 100
            prev_tw = (prev_target_weights.get(ticker) or 0) * 100
            prev_price = prev_last_prices.get(ticker)
            score_val = _score_num(last_report, ticker)
            prev_score_val = _score_num(previous_report, ticker)
            hold_rows.append([ticker, name, f"{cw:.1f}", f"{tw:.1f}", score_str(ticker), f"{price:,.0f}" if price is not None else "-"])
            hold_changes.append([
                0, 0,
                _diff(cw, prev_cw), _diff(tw, prev_tw), _diff(score_val, prev_score_val), _diff(price, prev_price),
            ])
        html_parts.append(_table(hold_headers, hold_rows, hold_changes))
    else:
        html_parts.append("<p>（なし）</p>")
    html_parts.append("")

    html_parts.append("<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">ウォッチリスト優先度（保有すべき順）</h3>")
    wl_tickers = [w["ticker"] for w in watchlist if isinstance(w, dict) and w.get("ticker")]
    if wl_tickers and portfolio_scores:
        wl_sorted = sorted(wl_tickers, key=lambda t: -(portfolio_scores.get(t) or 0))
        wl_headers = ["順位", "銘柄", "名前", "状態", "スコア", "株価(円)"]
        wl_rows = []
        wl_changes = []
        for i, ticker in enumerate(wl_sorted, 1):
            name = (ticker_names.get(ticker) or ticker)[:36]
            st = status_by_ticker.get(ticker, "WATCHING")
            price = last_prices.get(ticker)
            prev_price = prev_last_prices.get(ticker)
            score_val = _score_num(last_report, ticker)
            prev_score_val = _score_num(previous_report, ticker)
            wl_rows.append([i, ticker, name, st, score_str(ticker), f"{price:,.0f}" if price is not None else "-"])
            wl_changes.append([0, 0, 0, 0, _diff(score_val, prev_score_val), _diff(price, prev_price)])
        html_parts.append(_table(wl_headers, wl_rows, wl_changes))
    else:
        html_parts.append("<p>（データなし）</p>")
    html_parts.append("")

    recs = (draft.get("recommendations") or []) if isinstance(draft, dict) else []
    html_parts.append("<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">新規購入推奨</h3>")
    if not recs:
        html_parts.append("<p>（なし）</p>")
    else:
        html_parts.append(_table(["銘柄", "株数", "予想約定額"], [[_esc(str(r.get("ticker", ""))), str(r.get("shares", "")), str(r.get("amount_yen", ""))] for r in recs]))
    html_parts.append("")
    html_parts.append("<p>======================================</p>")
    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def build_report_body() -> str:
    """プレーンテキスト版（HTML 生成に失敗したときのフォールバック）。"""
    last_report = load_json(DATA_DIR / "last_report.json", {})
    run_status = load_json(DATA_DIR / "run_status.json", {})
    report_text = (last_report.get("report_text") or "").strip()
    if report_text:
        return f"【バッチ】{run_status.get('status', '?')} … {run_status.get('finished_at', '-')}\n\n" + report_text
    return "DPA 日次レポート（要約のみ。last_report を確認してください。）"


def send_report(service, to_email: str) -> None:
    """レポートを HTML メールで to_email 宛てに送信する。"""
    body_html = build_report_html()
    data_date = load_json(DATA_DIR / "last_report.json", {}).get("data_date", "")
    subject = f"DPA 日次レポート {data_date}" if data_date else "DPA 日次レポート"

    message = MIMEText(body_html, "html", "utf-8")
    message["To"] = to_email
    message["Subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"送信しました: {to_email}")


def main():
    creds = load_credentials()
    service = build("gmail", "v1", credentials=creds)

    # 自分宛て = 認証アカウントのメールアドレス
    profile = service.users().getProfile(userId="me").execute()
    to_email = profile.get("emailAddress")
    if not to_email:
        print("メールアドレスを取得できませんでした。", file=sys.stderr)
        sys.exit(1)

    send_report(service, to_email)


if __name__ == "__main__":
    main()

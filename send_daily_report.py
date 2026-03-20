#!/usr/bin/env python3
"""
DPA 日次レポートを Gmail で自分宛てに送信するスクリプト。

動き:
- 1) daily_routine（日次バッチ）を実行し、成功/失敗に応じて last_report.json / run_status.json を更新
- 2) 成功時: 更新されたレポート内容を HTML メールで送信
- 3) 失敗時: エラー内容のサマリを HTML メールで送信

初回実行時は credentials.json を読み込み、ブラウザで OAuth 認証後に token.json を保存する。
"""

import base64
import json
import os
import subprocess
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


def _table(
    headers: list[str],
    rows: list[list[str]],
    change_matrix: Optional[list[list[int]]] = None,
    *,
    numeric_columns: bool = False,
) -> str:
    """HTML テーブルを生成。change_matrix[i][j]: 1=増(赤文字), -1=減(緑文字), 0=色なし。枠線は常にグレー。
    numeric_columns=True のとき等幅＋数値列は右揃え（コード・銘柄名は左）。
    """
    table_style = "border-collapse:collapse; font-size:14px; border-color:#ccc;"
    if numeric_columns:
        table_style += " font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums;"
    h = f"<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" style=\"{table_style}\">"
    if numeric_columns:
        th_parts = []
        for i, x in enumerate(headers):
            align = "left" if i < 2 else "right"
            th_parts.append(
                f"<th style=\"background:#e0e0e0; border-color:#ccc; text-align:{align};\">{_esc(x)}</th>"
            )
        h += "<thead><tr>" + "".join(th_parts) + "</tr></thead><tbody>"
    else:
        h += "<thead><tr>" + "".join(
            f"<th style=\"background:#e0e0e0; border-color:#ccc;\">{_esc(x)}</th>" for x in headers
        ) + "</tr></thead><tbody>"
    for ri, row in enumerate(rows):
        cells = []
        for i, x in enumerate(row):
            if numeric_columns:
                align = "left" if i < 2 else "right"
                style = f" border-color:#ccc; text-align:{align};"
            else:
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
    draft_cap = draft.get("draft_budget_cap")
    avail_budget = draft.get("available_budget")  # 推奨買付合計（消費額）

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
            ("本日新規購入に使える理論上の最大額（売却見込み反映）", f"{raw_budget:,.0f} 円" if raw_budget is not None else "-"),
            ("ドラフト予算上限（PANIC 時は0）", f"{draft_cap:,.0f} 円" if draft_cap is not None else "-"),
            ("推奨買付合計（消費額）", f"{avail_budget:,.0f} 円" if avail_budget is not None else "-"),
        ]),
        "",
    ]

    purge = last_report.get("purge") or {}
    purge_items = purge.get("items") or []
    html_parts.append(
        "<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #2e7d32; color: #1b5e20;\">売却指示</h3>"
    )
    if not purge_items:
        html_parts.append("<p>（なし）</p>")
    else:
        purge_rows = []
        for x in purge_items:
            ticker = str(x.get("ticker", ""))
            name = (ticker_names.get(ticker) or "-")[:32]
            reason = str(x.get("reason_ja") or x.get("reason") or "-")
            price = x.get("current_price")
            price_str = f"{float(price):,.0f}" if price is not None else "-"
            sh = x.get("shares_to_sell")
            try:
                sh_int = int(sh) if sh is not None else 0
            except (TypeError, ValueError):
                sh_int = 0
            # 0 株＝実売却なし（アラートのみ）
            shares_str = f"{sh_int} 株" if sh_int > 0 else "-"
            purge_rows.append([ticker, name, reason, price_str, shares_str])
        html_parts.append(
            _table(
                ["コード", "銘柄名", "理由", "現在価格", "売却株数"],
                [[_esc(str(c)) for c in row] for row in purge_rows],
            )
        )
    html_parts.append("")

    recs = (draft.get("recommendations") or []) if isinstance(draft, dict) else []
    html_parts.append(
        "<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #c62828; color: #b71c1c;\">新規購入推奨</h3>"
    )
    if not recs:
        html_parts.append("<p>（なし）</p>")
    else:
        rows = []
        for r in recs:
            ticker = str(r.get("ticker", ""))
            name = str(r.get("name", "-"))[:32]
            shares = r.get("shares", 0)
            budget = r.get("budget_used") or r.get("amount_yen") or 0
            try:
                budget_str = f"{float(budget):,.0f}" if budget else "-"
            except (TypeError, ValueError):
                budget_str = "-"
            rows.append([ticker, name, f"{shares} 株", budget_str])
        html_parts.append(_table(["コード", "銘柄名", "株数", "予算（円）"], [[_esc(x) for x in row] for row in rows]))
    html_parts.append("")

    html_parts.append("<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">保有銘柄の状況</h3>")
    if current_weights:
        hold_headers = ["コード", "銘柄名", "現在%", "目標%(乖離pt)", "スコア", "株価(円)"]
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
            dev_pp = cw - tw
            tgt_cell = f"{tw:.1f} ({dev_pp:+.1f})"
            hold_rows.append([ticker, name, f"{cw:.1f}", tgt_cell, score_str(ticker), f"{price:,.0f}" if price is not None else "-"])
            hold_changes.append([
                0, 0,
                _diff(cw, prev_cw), _diff(tw, prev_tw), _diff(score_val, prev_score_val), _diff(price, prev_price),
            ])
        html_parts.append(_table(hold_headers, hold_rows, hold_changes, numeric_columns=True))
    else:
        html_parts.append("<p>（なし）</p>")
    html_parts.append("")

    html_parts.append("<h3 style=\"margin: 1em 0 0.3em 0; padding: 6px 0; border-bottom: 2px solid #1976d2; color: #1565c0;\">ウォッチリスト優先度（保有すべき順）</h3>")
    wl_tickers = [w["ticker"] for w in watchlist if isinstance(w, dict) and w.get("ticker")]
    if wl_tickers and portfolio_scores:
        wl_sorted = sorted(wl_tickers, key=lambda t: -(portfolio_scores.get(t) or 0))
        wl_headers = ["順位", "コード", "銘柄名", "状態", "スコア", "株価(円)"]
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


def run_daily_routine() -> tuple[bool, str]:
    """
    daily_routine（日次バッチ）を実行し、成功したかどうかとログ文字列を返す。
    - 戻り値 True: 正常終了（レポートメール送信）
    - 戻り値 False: 失敗（エラーレポートを送信）
    """
    cmd = [sys.executable, "-m", "daily_routine", "--config", "config.yaml"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60 * 30,  # 最大30分
        )
    except Exception as e:
        return False, f"Failed to start daily_routine: {e}"

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    log_parts: list[str] = []
    if stdout.strip():
        log_parts.append("=== STDOUT ===")
        log_parts.append(stdout.strip())
    if stderr.strip():
        log_parts.append("=== STDERR ===")
        log_parts.append(stderr.strip())
    log_parts.append(f"(exit_code={proc.returncode})")
    log = "\n".join(log_parts)

    # コンソールにも出しておく
    print(log, file=sys.stderr)
    return proc.returncode == 0, log


def build_failure_html(log: str) -> str:
    """日次バッチ失敗時のエラーメール本文（HTML）を生成。"""
    escaped_log = _esc(log or "No log output.")
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head>"
        "<body style=\"font-family: sans-serif; max-width: 720px;\">"
        "<h2 style=\"color:#c62828;\">DPA 日次バッチ失敗のお知らせ</h2>"
        "<p>今朝の DPA 日次バッチ実行に失敗したため、日次レポートは更新されていません。</p>"
        "<p>ログのサマリは次のとおりです（必要に応じてサーバー側のログも確認してください）。</p>"
        "<pre style=\"font-size:12px; background:#f5f5f5; padding:8px; white-space:pre-wrap;\">"
        f"{escaped_log}"
        "</pre>"
        "<p>スクリプト: daily_routine.py / send_daily_report.py</p>"
        "</body></html>"
    )


def _is_daily_report_email_enabled() -> bool:
    """config.yaml の daily_report.enabled を参照。未設定時は True（従来互換）。"""
    config_path = ROOT / "config.yaml"
    if not config_path.exists():
        return True
    try:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        email_cfg = cfg.get("daily_report") or {}
        return bool(email_cfg.get("enabled", True))
    except Exception:
        return True


def send_report(service, to_email: str) -> None:
    """
    日次バッチを実行し、その結果に応じて HTML メールを to_email 宛てに送信する。
    - 成功時: 通常の DPA 日次レポート（daily_report.enabled が false ならメール送信スキップ）
    - 失敗時: 失敗を通知するエラーレポート（同じく enabled で制御）
    """
    ok, log = run_daily_routine()

    if not _is_daily_report_email_enabled():
        print("設定によりメール送信はスキップされました（daily_report.enabled: false）")
        return

    if ok:
        body_html = build_report_html()
        data_date = load_json(DATA_DIR / "last_report.json", {}).get("data_date", "")
        subject = f"DPA 日次レポート {data_date}" if data_date else "DPA 日次レポート"
    else:
        body_html = build_failure_html(log)
        subject = "DPA 日次バッチ失敗のお知らせ"

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

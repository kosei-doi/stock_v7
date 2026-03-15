#!/usr/bin/env python3
"""
DPA 日次レポートを Gmail で自分宛てに送信するスクリプト。
初回実行時は credentials.json を読み込み、ブラウザで OAuth 認証後に token.json を保存する。
"""

import base64
import json
import os
import sys
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# プロジェクトルートをカレントにする（credentials.json / token.json / data/ の位置）
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"
DATA_DIR = ROOT / "data"


def load_credentials():
    """credentials.json と token.json で Gmail API 用の Credentials を取得。初回はブラウザで OAuth。"""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(f"credentials.json が見つかりません: {CREDENTIALS_FILE}", file=sys.stderr)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            # 固定ポートにしないと Google Cloud の「リダイレクト URI」と一致しない
            creds = flow.run_local_server(port=8080)
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


def build_report_body() -> str:
    """DPA の run_status / last_report / portfolio_state からレポート本文を組み立てる。"""
    run_status = load_json(DATA_DIR / "run_status.json", {})
    last_report = load_json(DATA_DIR / "last_report.json", {})
    portfolio = load_json(ROOT / "portfolio_state.json", {})

    lines = [
        "=== DPA 日次レポート ===",
        "",
    ]

    # バッチ実行ステータス
    lines.append("【バッチ実行ステータス】")
    lines.append(f"  状態: {run_status.get('status', '不明')}")
    lines.append(f"  メッセージ: {run_status.get('message', '-')}")
    if "step" in run_status and "total_steps" in run_status:
        lines.append(f"  ステップ: {run_status['step']} / {run_status['total_steps']}")
    lines.append(f"  完了日時: {run_status.get('finished_at', '-')}")
    lines.append("")

    # 直近レポート概要
    lines.append("【直近レポート概要】")
    lines.append(f"  作成日時: {last_report.get('created_at', '-')}")
    lines.append(f"  データ日: {last_report.get('data_date', '-')}")
    lines.append(f"  フェーズ: {last_report.get('phase_name_ja', last_report.get('phase', '-'))}")
    cash = last_report.get("cash_yen") or portfolio.get("cash_yen")
    total = last_report.get("total_capital_yen")
    equity = last_report.get("equity_value_yen")
    if cash is not None:
        lines.append(f"  現金: {cash:,.0f} 円")
    if total is not None:
        lines.append(f"  総資産: {total:,.0f} 円")
    if equity is not None:
        lines.append(f"  株価評価: {equity:,.0f} 円")
    lines.append("")

    # 保有銘柄サマリ（last_report にあれば上位のみ）
    current_weights = last_report.get("current_weights") or {}
    ticker_names = last_report.get("ticker_names") or {}
    if current_weights and ticker_names:
        lines.append("【保有銘柄（ウェイト順）】")
        sorted_tickers = sorted(
            current_weights.items(), key=lambda x: -x[1]
        )[:10]
        for ticker, w in sorted_tickers:
            name = ticker_names.get(ticker, ticker)
            lines.append(f"  {ticker}: {w*100:.2f}% - {name[:40]}")
        lines.append("")

    lines.append("--")
    lines.append("DPA Daily Report (send_daily_report.py)")
    return "\n".join(lines)


def send_report(service, to_email: str) -> None:
    """レポート本文を to_email 宛てに送信する。"""
    body = build_report_body()
    data_date = load_json(DATA_DIR / "last_report.json", {}).get("data_date", "")
    subject = f"DPA 日次レポート {data_date}" if data_date else "DPA 日次レポート"

    message = MIMEText(body, "plain", "utf-8")
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

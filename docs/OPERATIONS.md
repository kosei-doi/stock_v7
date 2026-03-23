# 運用手順（Operations）

このファイルは、日々の実行・監視・障害対応の実運用手順をまとめたものです。

## 1. 前提

- Python 3.9 以上（推奨 3.10+）
- `pip install -r requirements.txt` 実施済み
- `config.yaml`、`data/watchlist.json`、`portfolio_state.json` が存在

## 2. 日次運用の標準フロー

1. 日次バッチ実行（`daily_routine.py`）
2. `data/last_report.json` 更新確認
3. 必要なら Web 画面で内容確認（`/dashboard`, `/report`）
4. メール運用時は `send_daily_report.py` 実行（成功/失敗通知）

## 3. ローカル実行コマンド

### 3.1 Web 起動

```bash
python3 -m uvicorn web.main:app --host 127.0.0.1 --port 8000
```

### 3.2 日次バッチ実行

```bash
python3 daily_routine.py --no-llm -v
```

### 3.3 1銘柄 DVC 検証

```bash
python3 -m core.dvc.dvc_phase1 --ticker 7203.T --dry-run
```

### 3.4 メール送信（バッチ実行込み）

```bash
python3 send_daily_report.py
```

## 4. Web 画面での運用

- `dashboard`:
  - `日次バッチ実行` ボタンで `/api/run_batch` 実行
  - `/api/status` ポーリングで 1/7..7/7 進捗表示
- `settings`:
  - `config.yaml` と `portfolio_state.json` を更新
  - 主要運用パラメータ（`watchlist_max_items`, `purge_lot_threshold` 等）を変更
- `trade`:
  - 購入/売却記録を反映し、現金残高を更新

## 5. サーバー運用（手動デプロイ）

```bash
git pull
pip install -r requirements.txt
systemctl restart dpa_web
```

確認:

- `http://<host>:8000` が応答すること
- `/dashboard` の KPI が表示されること
- `/api/status` が JSON を返すこと

## 6. GitHub 経由の同期手順

ローカル修正を GitHub 経由でサーバーへ反映する標準手順です。

### 6.1 ローカル -> GitHub

```bash
git checkout -b feature/update-dpa-docs
git add .
git commit -m "Update DPA operations docs"
git push -u origin feature/update-dpa-docs
```

その後、GitHub で Pull Request を作成し、`main`（または運用ブランチ）へマージします。

### 6.2 GitHub -> サーバー反映（強制同期）

```bash
cd /path/to/stock_v7
git fetch origin
git checkout main
git reset --hard origin/main
git clean -fd
pip install -r requirements.txt
systemctl restart dpa_web
```

### 6.3 同期時の注意点

- `token.json` や `credentials.json` は GitHub に含めない（サーバー固有）
- `config.yaml` が環境ごとに異なる場合は、共通化できる項目のみ Git 管理する
- 強制同期はサーバー側の未コミット変更を破棄するため、必要なら事前バックアップを取る
- 反映後は `/dashboard` と `/report` の表示、`/api/status` を必ず確認する

## 7. Cron / Timer 運用例

### 6.1 バッチのみ（メールなし）

```bash
0 6 * * 1-5 cd /path/to/stock_v7 && /usr/bin/python3 daily_routine.py --no-llm >> logs/daily_routine.log 2>&1
```

### 6.2 メール込み（内部でバッチ実行）

```bash
10 6 * * 1-5 cd /path/to/stock_v7 && /usr/bin/python3 send_daily_report.py >> logs/send_daily_report.log 2>&1
```

## 8. OAuth 運用（Gmail）

- 必須ファイル:
  - `credentials.json`（Google Cloud 発行）
  - `token.json`（初回認証後に生成）
- `token.json` が失効・破損した場合:
  - `send_daily_report.py` 実行時に再認証へフォールバック
- ヘッドレス環境でブラウザが開けない場合:
  - ローカルで再認証して生成した `token.json` をサーバーへ配置

## 9. 監視ポイント

毎日確認する推奨ファイル:

- `data/run_status.json`: 実行状態（`running/completed/failed`）
- `data/last_report.json`: 生成結果
- `data/previous_report.json`: 前日比較元
- `data/scores_history.json`: スコア履歴更新
- `output/*.json`: 銘柄別 DVC 出力

## 10. よくある障害と対処

- `invalid_grant`（Gmail）:
  - `token.json` 再認証
- `sector_peers が見つかりません`:
  - `config.yaml` の `sector_peers_path` を確認
- `watchlist` が更新されない:
  - `watchlist.max_items` と `watchlist` JSON の構造不整合（`null` 等）を確認
- `売却が出ない`:
  - `target_weights`, `current_prices`, `purge_lot_threshold` と単元株条件を確認

## 11. 安全運用ルール

- 実行前バックアップ:
  - `data/watchlist.json`
  - `portfolio_state.json`
  - `config.yaml`
- 設定変更は少量ずつ行い、変更後に `daily_routine.py --no-llm -v` で検証
- 予算・売却閾値を大きく変更した日は `report` の推奨件数と金額を必ず目視確認

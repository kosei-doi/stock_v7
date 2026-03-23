# GitHub 経由で Mac と VPS をそろえる（DPA / ConoHa VPS）

このドキュメントの目的は次のとおりです。

1. リポジトリ内のファイルを **Mac ↔ GitHub ↔ VPS** で同じ状態に保つ（全同期優先）。
2. デプロイ手順（pull・依存・再起動）を迷わないようにする。

## 1. まず結論（3ステップ）

| やりたいこと | どこで |
|-------------|--------|
| Mac の変更を VPS に反映 | Mac: `add/commit/push` → VPS: `pull/reset` → 依存更新 → 再起動 |
| GitHub 最新を Mac に反映 | Mac: `git pull origin main` |
| GitHub 最新を VPS に反映 | VPS: `git pull origin main`（失敗時は強制同期） |

`main` ブランチを正とすると、追跡対象ファイルは `push/pull` で一致させられます。

## 2. 全同期を優先する運用方針

このプロジェクトでは、必要に応じて次も Git 管理対象に含めて同期します。

- `config.yaml`
- `token.json`
- `data/`
- `output/`
- `portfolio_state.json`

運用のコツ:

- 普段は **Mac で編集 -> push -> VPS は pull（または reset）だけ** にする
- VPS でバッチ実行後の `data/` を同期したい場合は、VPS 側でも commit/push する
- リポジトリはプライベート運用を前提にする

## 3. 前提（VPS）

- パス: `/opt/dpa_app`
- Python 3.9+（推奨 3.10+）
- Debian/Ubuntu で `externally-managed-environment` が出る場合は venv 必須

### 3.1 依存インストール（PEP 668 対応）

```bash
cd "/opt/dpa_app"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

補足:

- `source .venv/bin/activate` が無い場合は `python3 -m venv .venv` を再実行
- `python` コマンドが無い場合は `python3` を使う（venv 有効化後は `python` が使える）

## 4. 日常の更新フロー

### 4.1 Mac: 変更を GitHub に載せる

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"
git status
git add -A
git commit -m "Sync DPA files"
git push origin main
```

### 4.2 VPS: GitHub に合わせる（通常）

```bash
cd "/opt/dpa_app"
git pull origin main
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo systemctl restart dpa_web
```

## 5. VPS で `pull` が失敗するとき（強制同期）

`main` を正として、VPS の未コミット変更を破棄して合わせます。

```bash
cd "/opt/dpa_app"
git fetch origin
git checkout main
git reset --hard origin/main
git clean -fd -e .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
sudo systemctl restart dpa_web
```

注意:

- この操作で VPS の未コミット変更は消える
- 必要なら実行前にバックアップまたは `git stash` で退避する

## 6. Mac を GitHub に合わせる（サーバーで更新した後）

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"
git fetch origin
git pull origin main
```

## 7. 初回セットアップ

### 7.1 Mac から初回 push

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"
git init
git add .
git commit -m "Initial deploy: DPA app"
git remote add origin https://github.com/kosei-doi/stock_v7.git
git branch -M main
git push -u origin main
```

### 7.2 VPS 初回 clone

```bash
apt update && apt install -y git python3 python3-venv python3-pip
git clone https://github.com/kosei-doi/stock_v7.git /opt/dpa_app
cd /opt/dpa_app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 8. GitHub 接続エラー（VPS）

HTTPS 接続に失敗する場合は、送信 TCP 443 の許可を確認します。

確認コマンド:

```bash
curl -I https://github.com
```

`HTTP 200/301` 等が返れば到達できています。

## 9. Cron 運用例

### 9.1 バッチのみ

```cron
0 6 * * 1-5 cd "/opt/dpa_app" && "/opt/dpa_app/.venv/bin/python" daily_routine.py --no-llm >> logs/daily_routine.log 2>&1
```

### 9.2 メール込み

```cron
10 6 * * 1-5 cd "/opt/dpa_app" && "/opt/dpa_app/.venv/bin/python" send_daily_report.py >> logs/send_daily_report.log 2>&1
```

## 10. チェックリスト（デプロイ後）

- `git rev-parse HEAD` で VPS と GitHub のコミットが一致
- 依存更新済み（`python -m pip install -r requirements.txt`）
- `systemctl restart dpa_web` 済み
- `http://<VPS_IP>:8000` が応答
- `git status` がクリーン

## 11. 関連ドキュメント

- `docs/LOGIC.md`
- `docs/ARCHITECTURE.md`

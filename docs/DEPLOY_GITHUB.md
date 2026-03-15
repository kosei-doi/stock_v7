# DPA アプリ：GitHub 経由デプロイ手順（ConoHa VPS）

カフェなど SSH が使えない環境向け。「Mac → GitHub Push」「VPS ブラウザコンソール → Clone & 起動」の流れです。

---

## 1. 事前準備（.gitignore）

プロジェクトルートに `.gitignore` を用意済みです。次の内容が除外されます。

- **Python**: `venv/`, `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`
- **機密**: `.env`, `.env.*`, `*-key*.json`, `*credentials*`, `*secret*`, `config.yaml`
- **ローカルデータ**: `data/`, `output/`, `portfolio_state.json`（サーバー側で再作成）
- **OS/IDE**: `.DS_Store`, `.idea/`, `terminals/`, `agent-transcripts/`

Firebase の秘密鍵は `*-key*.json` や `*credentials*` に含まれる名前で保存していれば除外されます。別名の場合は `.gitignore` にそのファイル名を追加してください。

---

## 2. Mac 側での作業（GitHub へ Push）

リポジトリ: **https://github.com/kosei-doi/stock_v7** （プライベートの場合は Personal access token を用意）

ターミナルでプロジェクトルートに移動してから、以下を順に実行します。

```bash
cd /Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7

# リポジトリが未初期化の場合のみ
git init

# すべて追加（.gitignore で除外されたものは入らない）
git add .
git status
# 確認: venv, data, output, .env 等が一覧に含まれていないこと

git commit -m "Initial deploy: DPA FastAPI app for ConoHa VPS"

# リモートを追加
git remote add origin https://github.com/kosei-doi/stock_v7.git

# メインブランチ名が main の場合
git branch -M main
git push -u origin main
```

すでに `git init` 済みで別の `origin` がある場合は、`git remote add` は不要です。URL を変えたいときは次のようにします。

```bash
git remote set-url origin https://github.com/kosei-doi/stock_v7.git
git push -u origin main
```

---

## 3. ConoHa コンソール側（操作は最小限）

ConoHa の **Web ブラウザコンソール**に root でログインしたら、以下だけ実行します。

### 初回セットアップ（1行で完了）

コンソールに貼り付けて実行してください。

```bash
apt update && apt install -y git python3 python3-venv python3-pip && git clone https://github.com/kosei-doi/stock_v7.git /opt/dpa_app && bash /opt/dpa_app/scripts/setup_conoha.sh
```

- プライベートリポジトリの場合、`git clone` のときにユーザー名とパスワードを聞かれたら、**パスワードには GitHub の Personal access token** を入力します。
- この1行で「パッケージ更新・git/Python 導入 → Clone → venv・依存インストール → data/output 作成 → config.yaml 作成 → systemd 登録・起動」まで一括で行われます。
- 完了したらブラウザで `http://VPSのIP:8000` にアクセスします（ファイアウォールで 8000 番を開けておいてください）。

### 2回目以降の更新（1行）

Mac で `git push` したあと、ConoHa コンソールでは次の1行だけ実行すれば反映されます。

```bash
cd /opt/dpa_app && git pull origin main && source venv/bin/activate && pip install -r requirements.txt && deactivate && systemctl restart dpa_web
```

---

## まとめ

| 作業 | Mac | ConoHa コンソール |
|------|-----|-------------------|
| 初回 | Push（手順2） | 上記「初回セットアップ」の1行を貼って実行 |
| 更新 | `git push origin main` | 上記「2回目以降の更新」の1行を貼って実行 |

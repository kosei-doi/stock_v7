# DPA アプリ：GitHub 経由デプロイ（ConoHa VPS）

カフェなど SSH が使えない環境向け。**Mac で Push → VPS のブラウザコンソールで Pull** の流れです。

---

## 日常の更新フロー（これだけ覚えればOK）

### Mac：コードを直したら GitHub に反映

プロジェクトルートで実行します。

```bash
cd /Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7

git add .
git status          # 変更ファイルの確認（任意）
git commit -m "メッセージ（例: ダッシュボード修正）"
git push origin main
```

### VPS：GitHub の最新を取り込んで再起動

ConoHa の **ブラウザコンソール** に root でログインし、次の1行を貼り付けて実行します。

```bash
cd /opt/dpa_app && git pull origin main && source venv/bin/activate && pip install -r requirements.txt && deactivate && systemctl restart dpa_web
```

ブラウザで `http://VPSのIP:8000` を開き直せば反映されています。

---

## 初回だけ：Mac でリポジトリを GitHub に上げる

まだ `git init` や `origin` を設定していない場合だけ、以下を実行します。

```bash
cd /Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7

git init
git add .
git commit -m "Initial deploy: DPA app"
git remote add origin https://github.com/kosei-doi/stock_v7.git
git branch -M main
git push -u origin main
```

- プライベートリポジトリなら、Push 時に GitHub の **Personal access token** をパスワードとして入力します。
- すでに `origin` がある場合は `git remote add` は不要。URLを変えたいときは `git remote set-url origin https://github.com/kosei-doi/stock_v7.git` で変更できます。

---

## 初回だけ：VPS で Clone して起動する

ConoHa の **ブラウザコンソール** に root でログインし、次のどちらかを実行します。

**1行でまとめて実行（推奨）**

```bash
apt update && apt install -y git python3 python3-venv python3-pip && git clone https://github.com/kosei-doi/stock_v7.git /opt/dpa_app && bash /opt/dpa_app/scripts/setup_conoha.sh
```

**2行に分ける場合（コンソールで1行が切れるとき）**

```bash
apt update && apt install -y git python3 python3-venv python3-pip && git clone https://github.com/kosei-doi/stock_v7.git /opt/dpa_app
```

```bash
bash /opt/dpa_app/scripts/setup_conoha.sh
```

- プライベートリポジトリのときは、`git clone` でユーザー名とパスワードを聞かれたら、パスワードに **Personal access token** を入力します。
- 終わったらブラウザで `http://VPSのIP:8000` にアクセス。つながらない場合は ConoHa のファイアウォールで **TCP 8000** を開放してください。

---

## 補足：.gitignore で除外しているもの

次のものだけ GitHub に上げません（それ以外は Push されます）。

- `venv/`, `__pycache__/` など Python 周り
- `.env`, `.env.*`（API キー用）
- `.DS_Store`, `terminals/`, `agent-transcripts/`

`data/`, `output/`, `config.yaml`, `portfolio_state.json` は **リポジトリに含まれる**ので、Clone した VPS でもそのまま使えます。

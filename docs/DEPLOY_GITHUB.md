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

## VPS から GitHub に接続できないとき（git clone / git pull が失敗する）

ConoHa の **セキュリティグループ** で「送信（OUT）」が許可されていないと、VPS から GitHub（HTTPS 443）へ出られません。

### やること：送信（OUT）で HTTPS を許可する

1. ConoHa コントロールパネル → **ネットワーク** → **セキュリティグループ**
2. 対象 VPS に紐づいているセキュリティグループを開く
3. **ルールを追加**（＋ボタン）
4. 次のように設定して保存：
   - **方向**: **送信（OUT）**
   - **プロトコル**: **TCP**
   - **ポート**: **443**
   - **送信先**: **0.0.0.0/0**（すべての宛先へ HTTPS を許可）

これで `git clone` / `git pull` で GitHub（https://github.com）へ接続できるようになります。

### 動作確認（VPS コンソールで）

```bash
curl -I https://github.com
```

`HTTP/2 200` や `HTTP/1.1 301` などが返れば OK。タイムアウトや「Connection refused」の場合は、上記ルールが反映されているか・別のファイアウォールがないか確認してください。

---

## 日次レポートメール（cron）

毎朝 7 時に `send_daily_report.py` で Gmail 自分宛てに DPA レポートを送るには、本番 VPS（Ubuntu）で cron を設定します。

### 設定方法

1. VPS にログインし、`crontab -e` を実行する（編集するユーザーで実行。アプリを動かしているユーザーか root で）。
2. 次の 1 行を追加して保存する。

```cron
0 7 * * * cd /opt/dpa_app && /opt/dpa_app/venv/bin/python send_daily_report.py
```

- `0 7 * * *` ＝ 毎日 7 時 0 分（サーバーのタイムゾーン。JST なら 7:00 JST）。
- アプリのパスが違う場合は `cd` と `venv` のパスを実際のディレクトリに合わせる。

### 初回だけ

- **初回実行時**は OAuth のためブラウザ認証が必要です。VPS ではブラウザを開けないので、**Mac などローカルで一度** `python send_daily_report.py` を実行し、認証して `token.json` を生成してから、その `token.json` をリポジトリにコミットして VPS にデプロイするか、手動で VPS の `/opt/dpa_app/` に置いてください。その後は cron からその `token.json` で送信されます。

---

## 補足：.gitignore で除外しているもの

次のものだけ GitHub に上げません（それ以外は Push されます）。

- `venv/`, `__pycache__/` など Python 周り
- `.env`, `.env.*`（API キー用）
- `.DS_Store`, `terminals/`, `agent-transcripts/`

`data/`, `output/`, `config.yaml`, `portfolio_state.json` は **リポジトリに含まれる**ので、Clone した VPS でもそのまま使えます。

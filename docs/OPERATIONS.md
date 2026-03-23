# GitHub 経由で Mac と VPS をそろえる（DPA / ConoHa VPS）

このドキュメントの目的は次のとおりです。

1. **リポジトリ内のファイルをすべて** **Mac ↔ GitHub ↔ VPS** で同じ状態に保つ（**全同期を最優先**。プライベートリポジトリ前提で `config.yaml`・`token.json`・`data/` なども Git で揃える）。
2. そのうえで、デプロイ手順（`pull`・依存・再起動）を迷わないようにする。

---

## まず結論（3ステップ）

| やりたいこと | どこで |
|-------------|--------|
| ① Mac で直したコードをサーバーにも反映 | Mac: `git add` → `commit` → `push` → **VPS: `git pull`** → 依存更新・サービス再起動 |
| ② GitHub 上の最新と手元をそろえる | Mac: `git pull origin main` |
| ③ VPS 上のファイルを GitHub と同じにする | VPS: `git pull origin main`（下記「pull が失敗するとき」参照） |

**GitHub の `main` ブランチ**を「正」とすると、**追跡しているファイルはすべて** Mac と VPS で `push` / `pull` だけで一致させられます。

---

## 全同期を優先する場合（このプロジェクトの推奨）

**コードだけでなく、次もコミットして GitHub 経由で揃えます。**（リポジトリは **プライベート** を推奨。公開リポジトリにはしないでください。）

| ファイル・ディレクトリ | 役割 |
|------------------------|------|
| `config.yaml` | 本番・開発の設定。Mac と VPS で同じ内容にしたいときはそのままコミット |
| `token.json` | Gmail OAuth など。同期対象に含める |
| `data/`・`output/` | 日次バッチの生成物・履歴。Mac と VPS で同じ状態にしたいときはコミット |
| `portfolio_state.json` | 現金残高など。同期対象に含める |

**運用のコツ**

- どちらか一方でしか更新しない、と決めると楽です（例: **普段は Mac で編集 → `push` → VPS は `pull` のみ**）。VPS 上だけでファイルをいじると、次回 `pull` でコンフリクトや上書きが起きやすくなります。
- **VPS でバッチを回したあと**にサーバー側の `data/` などを GitHub に載せたい場合は、VPS で `git add` → `commit` → `push`（または Mac に取り込んでから Mac から `push`）します。

### 補足：`rsync` は不要なことが多い

上記をすべて Git で追跡するなら、**`rsync` でデータをコピーする必要は基本的にありません。** Git が使えない環境だけ、従来どおり手動コピーで代用できます。

---

## 日常の更新フロー（これだけ覚えればよい）

### A. Mac：変更を GitHub に載せる

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"

git status
git add -A
git commit -m "説明（例: 設定・データ含む同期）"
git push origin main
```

- **全同期**なら `config.yaml`・`token.json`・`data/`・`output/`・`portfolio_state.json` も忘れずにコミット対象に含めます（`git status` で未追跡・変更が残っていないか確認）。

### B. VPS：GitHub の内容とディレクトリをそろえる

ConoHa の **ブラウザコンソール** などで root またはデプロイユーザーにログインし:

```bash
cd /opt/dpa_app

git pull origin main

source .venv/bin/activate
python -m pip install -r requirements.txt
deactivate

sudo systemctl restart dpa_web
```

アプリのパスが `/opt/dpa_app` でない場合は `cd` を読み替えます。

ブラウザで `http://VPSのIP:8000` を開き直し、反映を確認します。

---

## VPS で `git pull` が止まるとき

**未コミットのローカル変更**や **マージコンフリクト**で `pull` が止まることがあります。

### まず試す（通常）

```bash
cd /opt/dpa_app
git pull origin main
```

コンフリクトが出たら、**GitHub 上の `main` を正**にするなら、VPS 上の変更を捨ててリモートに合わせます（**VPS の未コミット変更は消えます**）。

```bash
cd /opt/dpa_app
git fetch origin
git reset --hard origin/main
git clean -fd -e .venv
source .venv/bin/activate && python -m pip install -r requirements.txt && deactivate
sudo systemctl restart dpa_web
```

- 全同期運用では、**本当に欲しい状態はすべて GitHub に `push` 済み**にしてから VPS で上記を実行するのが安全です。
- VPS だけにあった未コミットの編集を残したい場合は、先に `git stash` や別ディレクトリへコピーで退避してください。

---

## Mac 側を GitHub に合わせる（サーバーで直したあとなど）

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"
git fetch origin
git pull origin main
```

ローカルに未コミットの変更があるとマージや競合のメッセージが出ます。不要なら `git stash` や別ブランチで退避してから `pull` してください。

---

## 初回だけ：Mac から GitHub にリポジトリを載せる

まだ `remote` がない場合の例です。

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"
git init
git add .
git commit -m "Initial deploy: DPA app"
git remote add origin https://github.com/kosei-doi/stock_v7.git
git branch -M main
git push -u origin main
```

- プライベートリポジトリでは **Personal access token** をパスワードとして使うことがあります。
- 既に `origin` がある場合は `git remote add` は不要です。URL 変更は  
  `git remote set-url origin https://github.com/kosei-doi/stock_v7.git`

---

## 初回だけ：VPS で Clone して起動する

**ブラウザコンソール**で root ログイン後、次のいずれか。

**1行（推奨）**

```bash
apt update && apt install -y git python3 python3-venv python3-pip && git clone https://github.com/kosei-doi/stock_v7.git /opt/dpa_app && bash /opt/dpa_app/scripts/setup_conoha.sh
```

**2行に分ける場合**

```bash
apt update && apt install -y git python3 python3-venv python3-pip && git clone https://github.com/kosei-doi/stock_v7.git /opt/dpa_app
```

```bash
bash /opt/dpa_app/scripts/setup_conoha.sh
```

- プライベートリポジトリの `git clone` では、パスワード欄に **Personal access token** を入力します。
- ファイアウォールで **TCP 8000** を開放してください。

---

## VPS が GitHub に接続できないとき（clone / pull が失敗）

ConoHa の **セキュリティグループ** で **送信（OUT）の TCP 443** が許可されていないと、HTTPS で GitHub に出られません。

1. コントロールパネル → **ネットワーク** → **セキュリティグループ**
2. 対象 VPS のグループを開く → **ルールを追加**
3. **方向**: 送信（OUT） / **プロトコル**: TCP / **ポート**: **443** / **送信先**: `0.0.0.0/0`

確認:

```bash
curl -I https://github.com
```

`HTTP/2 200` や `301` などが返ればよいです。

---

## 日次レポートメール（cron）

VPS で毎朝メールを送る例（パスは環境に合わせる）:

```cron
0 7 * * * cd /opt/dpa_app && /opt/dpa_app/.venv/bin/python send_daily_report.py
```

- タイムゾーンはサーバーの設定に依存します（JST なら 7:00 JST）。
- **初回 OAuth** はブラウザが必要なので、**Mac で一度** `send_daily_report.py` を実行して `token.json` を生成し、**コミットして `push`** すれば VPS の `git pull` で同じ `token.json` が揃います。

---

## 現在の `.gitignore` のメモ

リポジトリの `.gitignore` には例えば次が含まれます（詳細は `/.gitignore` を参照）。

- `venv/`・`__pycache__/`・`.pytest_cache/`
- `.env`・`.env.*`（API キーを `.env` に書く場合）
- `.DS_Store`・IDE 用ディレクトリ

**全同期運用では**、`config.yaml`・`token.json`・`data/`・`output/`・`portfolio_state.json` は **`.gitignore` に入れない**（または追跡済みのまま）にして、普通に `git add` できる状態にしておきます。

---

## チェックリスト（デプロイ後）

- [ ] `git log` で VPS と GitHub が同じコミットか確認（`git rev-parse HEAD`）
- [ ] `python -m pip install -r requirements.txt` 済み
- [ ] `systemctl restart dpa_web`（または使っているプロセス管理）済み
- [ ] `http://VPSのIP:8000` が開く
- [ ] `git pull` 後に `config.yaml`・`token.json`・`data/` などが **GitHub の最新コミットと一致**している（必要なら `git status` でクリーン）

---

## 関連ドキュメント

- ロジック: `docs/LOGIC.md`
- 構成図: `docs/ARCHITECTURE.md`
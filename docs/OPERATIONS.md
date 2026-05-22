# GitHub 経由で Mac と VPS をそろえる（DPA / ConoHa VPS）

このドキュメントの目的は次のとおりです。

1. **コードと設定**を **Mac ↔ GitHub ↔ VPS** で `git push` / `git pull` により揃える（**日常デプロイは VPS で `git pull`**）。
2. **機密ファイル**（`token.json`・`credentials.json`・`.env`）は **Git に載せない**（各環境で手動配置または安全な経路でコピー）。
3. `config.yaml` や `data/`・`output/` はプライベートリポジトリなら Git で揃えてもよいが、機密管理と矛盾しないよう `.gitignore` を確認する。

---

## まず結論（3ステップ）


| やりたいこと                      | どこで                                                                     |
| --------------------------- | ----------------------------------------------------------------------- |
| ① Mac で直したコードをサーバーにも反映      | Mac: `git add` → `commit` → `push` → **VPS: `git pull`** → 依存更新・サービス再起動 |
| ② GitHub 上の最新と手元をそろえる       | Mac: `git pull origin main`                                             |
| ③ VPS 上のファイルを GitHub と同じにする | VPS: `git pull origin main`（下記「pull が失敗するとき」参照）                         |


**GitHub の `main` ブランチ**を「正」とすると、**追跡しているファイル**は Mac と VPS で `push` / `pull` だけで一致させられます。

---

## Git で揃えるもの・揃えないもの

| 種別 | ファイル・ディレクトリ | 方針 |
| ---- | ---------------------- | ---- |
| コード | `web/`・`core/`・スクリプトなど | **必ず Git**（日常デプロイは `git pull`） |
| 設定 | `config.yaml` | プライベートリポジトリなら **Git で揃えてよい** |
| データ | `data/`・`output/`・`portfolio_state.json` | 必要なら Git で揃える（**どちらか一方で編集**と決める） |
| 機密 | `token.json`・`credentials.json`・`.env` | **Git 非推奨**（`.gitignore` 対象。各環境で手動配置） |

**運用のコツ**

- 普段は **Mac で編集 → `push` → VPS は `git pull` のみ**。
- VPS 上だけで `data/` などを更新したあと GitHub に載せたい場合は、VPS で `git add` → `commit` → `push`（または Mac に取り込んでから `push`）。
- 機密は `scp` や ConoHa コンソール経由で VPS に置き、リポジトリにはコミットしない。

### 補足：`rsync` / `deploy.sh` は初回・レガシー用

**日常運用では `git pull` を使い、`deploy.sh`（Mac からの rsync）は初回配置や Git が使えないときだけ**使います。`deploy.sh` は `data/`・`output/`・機密ファイルを rsync から除外するため、本番データの上書きも起きにくい設計です。

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

- `config.yaml` や `data/` を Git で揃える場合は、コミット対象に含める（`git status` で未追跡・変更が残っていないか確認）。**`token.json`・`credentials.json`・`.env` はコミットしない。**

### B. VPS：GitHub の内容とディレクトリをそろえる

ConoHa の **ブラウザコンソール** などで root またはデプロイユーザーにログインし:

```bash
cd /opt/dpa_app

git pull origin main

# 初回のみ（venv が無ければ作成）
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
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
git clean -fd -e venv
[ -d venv ] || python3 -m venv venv
source venv/bin/activate && python -m pip install --upgrade pip && python -m pip install -r requirements.txt && deactivate
sudo systemctl restart dpa_web
```

- **本当に欲しい状態は GitHub に `push` 済み**にしてから VPS で上記を実行するのが安全です（機密ファイルは Git 外のため、別途 VPS に存在することを確認）。
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

## 初回・レガシー：`deploy.sh`（Mac から rsync）

Git clone 前や、Git が使えない環境へコードだけ送るときの **補助手段**です。**日常のデプロイは VPS で `git pull` を使ってください。**

```bash
cd "/Users/user/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"

export VPS_IP="あなたのVPSのIP"
export REMOTE_USER="root"
export REMOTE_DIR="/opt/dpa_app"

chmod +x deploy.sh
./deploy.sh
```

- 環境変数 `VPS_IP`・`REMOTE_USER`・`REMOTE_DIR` は **必須**（未設定時はエラー終了）。
- rsync は `token.json`・`credentials.json`・`.env`・`data/`・`output/` を **除外**する。
- `--delete` は **使わない**（リモートのデータ・手動配置した機密を消す危険があるため）。

初回セットアップ後は VPS 側で `git clone` し、以降は **`git pull` に切り替える**ことを推奨します。

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
0 7 * * * cd /opt/dpa_app && /opt/dpa_app/venv/bin/python send_daily_report.py
```

- タイムゾーンはサーバーの設定に依存します（JST なら 7:00 JST）。
- **初回 OAuth** はブラウザが必要なので、**Mac で一度** `send_daily_report.py` を実行して `token.json` を生成し、**Git には載せず** `scp` 等で VPS の `/opt/dpa_app/token.json` に配置します。

---

## 現在の `.gitignore` のメモ

リポジトリの `.gitignore` には例えば次が含まれます（詳細は `/.gitignore` を参照）。

- `venv/`・`__pycache__/`・`.pytest_cache/`
- `.env`・`.env.*`（API キーを `.env` に書く場合）
- `token.json`・`credentials.json`（OAuth / API 資格情報）
- `.DS_Store`・IDE 用ディレクトリ

**既に Git で追跡されている機密**がある場合は、ファイルを残したまま index から外します:

```bash
git rm --cached token.json credentials.json
git commit -m "Stop tracking OAuth credentials"
```

`config.yaml` や `data/` を Git で揃える場合は、`.gitignore` に入れない（追跡対象のまま）にします。

---

## チェックリスト（デプロイ後）

- `git log` で VPS と GitHub が同じコミットか確認（`git rev-parse HEAD`）
- `[ -d venv ] || python3 -m venv venv` 実行済み
- `source venv/bin/activate && python -m pip install -r requirements.txt && deactivate` 済み
- `systemctl restart dpa_web`（または使っているプロセス管理）済み
- `http://VPSのIP:8000` が開く
- `git pull` 後に `config.yaml`・`data/` などが **GitHub の最新コミットと一致**している（必要なら `git status` でクリーン）
- Mac / VPS とも `git ls-files` に `token.json`・`credentials.json` が**含まれない**（追跡外化済みであること）
- `token.json` 等の機密が VPS に **手動配置済み**である

---

## 関連ドキュメント

- ロジック: `docs/LOGIC.md`
- 構成図: `docs/ARCHITECTURE.md`


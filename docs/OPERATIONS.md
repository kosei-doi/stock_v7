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

## 本番セキュリティ（Issue #2）

本番 VPS では **API キー認証** と **ファイアウォールで 8000 を自宅 IP のみ** に制限します。TLS（HTTPS）は後続で nginx + Let's Encrypt または Cloudflare Tunnel を検討してください（当面は `http://VPSのIP:8000`）。

**注意:** `DPA_API_KEY` を有効にすると、同一オリジンの HTML にキーが埋め込まれます（`dpaFetch` が `X-API-Key` を送るため）。単一ユーザー・IP 制限前提です。キーは Git に載せず、`/etc/dpa-app/dpa.env` のみに置きます。

### 1. API キーと systemd 環境変数（VPS）

```bash
# キー生成（Mac でも VPS でも可）
openssl rand -hex 32

sudo mkdir -p /etc/dpa-app
sudo cp /opt/dpa_app/scripts/dpa.env.example /etc/dpa-app/dpa.env
sudo chmod 600 /etc/dpa-app/dpa.env
sudo nano /etc/dpa-app/dpa.env   # DPA_API_KEY を実値に差し替え
```

`/etc/dpa-app/dpa.env` の例:

```env
DPA_ENV=production
DPA_API_KEY=<openssl で生成した値>
```

`scripts/dpa_web.service` は `EnvironmentFile=-/etc/dpa-app/dpa.env` を読みます（ファイルが無い場合はスキップ＝開発モード相当）。

```bash
cd /opt/dpa_app
sudo cp scripts/dpa_web.service /etc/systemd/system/dpa_web.service
sudo systemctl daemon-reload
sudo systemctl restart dpa_web
sudo systemctl status dpa_web --no-pager
```

`DPA_ENV=production` 時は `/docs` 等の OpenAPI UI は出ません（404）。

### 2. ファイアウォール（UFW + ConoHa）

**UFW（VPS 内）** — `YOUR_HOME_IP` を自宅のグローバル IP に置き換え:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow from YOUR_HOME_IP to any port 8000 proto tcp
sudo ufw enable
sudo ufw status
```

**ConoHa セキュリティグループ**（コントロールパネル）でも **受信 TCP 8000** を同様に自宅 IP のみに制限してください。送信 OUT 443 は [VPS が GitHub に接続できないとき](#vps-が-github-に接続できないときclone--pull-が失敗) を参照。

自宅 IP が変わったとき:

```bash
sudo ufw delete allow from OLD_IP to any port 8000 proto tcp
sudo ufw allow from NEW_IP to any port 8000 proto tcp
```

### 3. 受入確認（curl）

VPS 上または自宅から（`VPS_IP`・`KEY` を置き換え）:

```bash
# キーなし → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://127.0.0.1:8000/api/trade/purchase" \
  -H "Content-Type: application/json" \
  -H "X-DPA-Client: 1" \
  -d '{"ticker":"7203","shares":1,"price":1000}'

# キーあり・X-DPA-Client なし → 403
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://127.0.0.1:8000/api/trade/purchase" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: KEY" \
  -d '{"ticker":"7203","shares":1,"price":1000}'
```

ブラウザ（自宅 IP から）で `http://VPSのIP:8000` を開き、取引・設定保存・ダッシュボードのバッチ実行が成功することを確認します。

### 4. デプロイ後（git pull）

本番化のコードを反映したあとは、既存の [日常の更新フロー](#日常の更新フローこれだけ覚えればよい) のとおり `git pull` → 依存更新 → `systemctl restart dpa_web` です。`/etc/dpa-app/dpa.env` は **Git で上書きされません**（手動維持）。

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
- 本番: `/etc/dpa-app/dpa.env` に `DPA_ENV=production` と `DPA_API_KEY` が設定済み
- 本番: UFW / ConoHa で **8000 は自宅 IP のみ**（上記 [本番セキュリティ](#本番セキュリティissue-2)）
- 本番: `curl` でキーなし POST が **401**、ブラウザから POST が成功

---

## 本番 DB 切替（SQLite / DB-6〜8）

JSON を SoT から SQLite へ移す手順。詳細は [`docs/ADR-001-database.md`](ADR-001-database.md) を参照。

### 移行対象（`data/dpa.db` に取り込む）

| ソース | テーブル / Repository |
|--------|------------------------|
| `data/watchlist.json` | `watchlist_items` |
| `portfolio_state.json` | `portfolio_state` |
| `data/last_report.json` / `previous_report.json` | `daily_reports` |
| `data/scores_history.json` | `score_history_entries` |
| `data/run_status.json` | `run_jobs` |
| `data/daily_cache.json`（任意・大） | `market_cache` |
| `data/sector_peers.json` | `sector_peers` |
| `output/*.json` | `ticker_analyses` |

**運用メモ:** `git pull` は**コードのみ**同期する。VPS 上の `data/`・`output/`・`data/dpa.db` はローカル実データのため、Mac と Git で二重管理しない。Mac で試す場合も同手順で `--data-dir` にプロジェクトルートを指定できる。

### 1. バックアップ（VPS）

```bash
cd /opt/dpa_app
sudo systemctl stop dpa_web
cp -a data data.bak.$(date +%Y%m%d)
cp -a portfolio_state.json portfolio_state.json.bak
cp -a output output.bak.$(date +%Y%m%d)   # 任意
cp -a data/dpa.db data/dpa.db.bak 2>/dev/null || true
```

### 2. ドライラン（件数確認のみ）

```bash
cd /opt/dpa_app
source venv/bin/activate
python scripts/migrate_json_to_db.py --data-dir /opt/dpa_app --dry-run
```

ログで watchlist 件数・現金残高・`last_report.data_date`・score_history 行数・`output/*.json` 件数を確認する。

### 3. import

一括ラッパー（推奨）:

```bash
chmod +x scripts/migrate_production.sh
APP_DIR=/opt/dpa_app ./scripts/migrate_production.sh
# JSON 退避まで自動: APP_DIR=/opt/dpa_app ./scripts/migrate_production.sh --archive-json
```

手動で行う場合:

```bash
python scripts/migrate_json_to_db.py --data-dir /opt/dpa_app
python scripts/verify_db_migration.py --data-dir /opt/dpa_app
# JSON を退避する場合（推奨・成功後のみ）:
# python scripts/migrate_json_to_db.py --data-dir /opt/dpa_app --archive-json
```

`verify_db_migration.py` は import 直後・`DPA_PERSISTENCE=sqlite` 切替前に実行し、JSON と DB の件数・現金・`data_date` が一致することを確認する。不一致時は exit 1。

### 4. 切替・再起動

`/etc/dpa-app/dpa.env`（[`scripts/dpa.env.example`](../scripts/dpa.env.example) 参照）:

```bash
DPA_PERSISTENCE=sqlite
DPA_DATABASE_URL=sqlite:////opt/dpa_app/data/dpa.db
```

```bash
sudo systemctl restart dpa_web
```

### 5. ロールバック

- `DPA_PERSISTENCE` を外す（または `file`）→ `systemctl restart dpa_web`
- `data.bak.*` / `output.bak.*` から JSON を復元

`data/dpa.db` は Git に含めない（`.gitignore` 済み）。

### 6. 移行後の整合チェック（受入）

切替・再起動後、次を確認する。

**ブラウザ（自宅 IP から）**

- [ ] ダッシュボード（`/`）が開き、レポート要約が表示される
- [ ] レポート（`/report`）、取引（`/trade`）、企業分析（`/analyze`）、ウォッチリスト（`/watchlist`）がエラーなく表示される

**API（VPS 上または SSH トンネル）**

```bash
curl -s http://127.0.0.1:8000/api/status | head
curl -s http://127.0.0.1:8000/api/report/merged | head
curl -s http://127.0.0.1:8000/api/watchlist | head
```

- [ ] `status` が `idle` または直近バッチ結果と一致
- [ ] `report/merged` の `report.data_date` が移行前の `last_report.json` と一致
- [ ] `watchlist` の銘柄数が移行前と一致

**DB（VPS）**

```bash
cd /opt/dpa_app
sqlite3 data/dpa.db "SELECT COUNT(*) FROM watchlist_items;"
sqlite3 data/dpa.db "SELECT cash_yen FROM portfolio_state WHERE id=1;"
sqlite3 data/dpa.db "SELECT data_date FROM daily_reports WHERE report_kind='last';"
sqlite3 data/dpa.db "SELECT COUNT(*) FROM ticker_analyses;"
```

- [ ] 現金残高・保有銘柄数・最新 `data_date`・分析件数が dry-run ログと一致

**バッチ**

- [ ] 画面から日次バッチを 1 回実行し、`/api/status` が `completed` になる（またはメール通知が届く）

問題がある場合は [§5 ロールバック](#5-ロールバック) のとおり `DPA_PERSISTENCE` を `file` に戻し、`.bak` から JSON を復元する。

---

## 関連ドキュメント

- ロジック: `docs/LOGIC.md`
- 構成図: `docs/ARCHITECTURE.md`
- DB 設計: `docs/ADR-001-database.md`


# Issue バックログ（修正タスク一覧）

レビュー・実装計画（`IMPLEMENTATION_PLAN.md`）完了後の**残タスク**と、今後の改善案。  
GitHub Issue 作成時は下記タイトル・本文をそのまま使えます。

**ラベル案:** `security` `bug` `enhancement` `ops` `tests` `docs`

---

## 優先度 P0（セキュリティ・本番前必須）

~~Issue 1（機密除去・OAuth ローテーション）~~ — **対応しない（GitHub #1 クローズ済み）**

### Issue 2: 本番 VPS に API 認証・ネットワーク制限を適用する

**Labels:** `security`, `ops`

**本文:**

```markdown
## 背景
- `DPA_API_KEY` 認証は実装済み（未設定時は開発モードでスキップ）
- `dpa_web.service` は `0.0.0.0:8000` で待ち受け

## タスク
- [ ] VPS に `DPA_ENV=production` と `DPA_API_KEY` を systemd Environment に設定
- [ ] ファイアウォールで 8000 を必要最小限に（VPN / SSH トンネル / IP 許可）
- [ ] nginx + Let's Encrypt または Cloudflare Tunnel で TLS
- [ ] `git pull` 後の再起動手順を OPERATIONS で確認

## 受入条件
- インターネットから無認証で POST `/api/trade/*` できない
- ブラウザは HTTPS でアクセス可能（方針に応じて）
```

---

## 優先度 P1（バグ・未コミット修正）

### Issue 3: Starlette 1.0 向け TemplateResponse 呼び出しを修正してコミットする

**Labels:** `bug`

**本文:**

```markdown
## 背景
- Starlette 1.0 では `TemplateResponse(request, name, context)` が必須
- 旧 API のままだと `/` `/dashboard` 等が 500（Jinja cache TypeError）
- ローカルで `web/main.py` は修正済みだが **未コミット**

## タスク
- [ ] `web/main.py` の全 `TemplateResponse` を新 API に統一（済なら diff 確認のみ）
- [ ] 手動で `/` `/report` `/trade` が 200 になることを確認
- [ ] コミット・push

## 受入条件
- 全 HTML ルートが 200
- CI / pytest 既存 54 件が通過
```

---

## 優先度 P2（品質・運用）

### Issue 4: API の Pydantic 化と settings バリデーション強化

**Labels:** `enhancement`

**本文:**

```markdown
## 背景
- `trade_purchase` / `trade_sale` は Pydantic 化済み
- その他 POST は `body: dict` のまま。範囲外値のサイレント無視あり

## タスク
- [ ] `/api/settings/update` 等に Pydantic モデル
- [ ] 範囲外・型不正は 422
- [ ] `TestClient` テスト追加

## 受入条件
- 不正 body で 422
- `pytest tests/ -q` 全通過
```

---

### Issue 5: CSRF 対策と API レート制限（特に run_batch）

**Labels:** `enhancement`, `security`

**本文:**

```markdown
## タスク
- [ ] `slowapi` 等で `/api/run_batch` にレート制限
- [ ] ブラウザ向け POST に CSRF トークンまたは SameSite + カスタムヘッダ方針を決定・実装

## 受入条件
- 短時間の連続 batch POST が 429 等で制限される
```

---

### Issue 6: 日次バッチ・run_draft の統合テスト追加

**Labels:** `tests`

**本文:**

```markdown
## 背景
- 単体テスト 54 件は通過
- `daily_routine` 統合、`run_draft` の予算連鎖は未カバー

## タスク
- [ ] `test_daily_routine_integration.py`（fixture + mock yfinance 等）
- [ ] purge → draft 予算連鎖のスモーク

## 受入条件
- CI で `pytest tests/ -q` 通過
```

---

### Issue 7: 既存追跡ファイルの Git index 整理（OPERATIONS 手順の実施）

**Labels:** `ops`, `docs`

**本文:**

```markdown
## 背景
- `.gitignore` に `token.json` / `credentials.json` は追加済み
- 既に追跡中のファイルは `git rm --cached` が必要（OPERATIONS に手順記載想定）

## タスク
- [ ] `git rm --cached` 実施と push
- [ ] OPERATIONS の手動手順セクションを実運用で検証

## 受入条件
- `git ls-files` に機密ファイルが含まれない
```

---

---

## Epic: ファイル永続化 → データベース移行

**方針:** トランザクション系・履歴系は RDB に集約。機密（OAuth）は DB に入れない。`config.yaml` は Phase 1 では維持し、必要なら後続 Issue で settings テーブル化。

### 本番（デプロイ中）データ移行 — Epic 共通要件（全 DB Issue に適用）

**必須:** ローカル開発用の空 DB だけでなく、**いま VPS（例: `/opt/dpa_app`）で運用中の JSON データを失わず DB に取り込める**こと。

| 要件 | 内容 |
|------|------|
| 移行元 | 本番ディレクトリの `data/*.json`, `portfolio_state.json`, `output/*.json`（`config.yaml` は任意） |
| 移行先 | 本番と同じ PostgreSQL（または方針決定後の DB） |
| 手順 | ① 本番バックアップ ② import スクリプト ③ 件数・代表値の検証 ④ アプリを DB モードで再起動 |
| ダウンタイム | 短時間停止または read-only ウィンドウを想定し、手順を `OPERATIONS.md` に記載 |
| ロールバック | import 前の JSON を `.bak` 退避し、DB 切替失敗時はファイルモードに戻せる |
| 実行場所 | VPS 上で実行する手順を第一とし、必要なら Mac → rsync/scp で export してから import も可 |

**GitHub:** 横断 Issue → [#15 本番デプロイ済みデータの DB 移行](https://github.com/kosei-doi/stock_v7/issues/15)（#8〜#14 とリンク）

### 現状のファイル保管（移行対象の整理）

| データ | パス | 主な読み書き | DB 化の優先度 |
|--------|------|--------------|---------------|
| ウォッチリスト・保有 | `data/watchlist.json` | `watchlist_io`, `web/api` | **P0**（競合・取引と直結） |
| 現金残高 | `portfolio_state.json` | `web/api`, `daily_routine` | **P0** |
| 日次レポート | `data/last_report.json`, `previous_report.json` | `daily_routine`, `web/api` | P1 |
| スコア履歴 | `data/scores_history.json` | `dpa_scores`, `dvc_batch` | P1 |
| バッチ進捗 | `data/run_status.json` | `web/api`, `send_daily_report` | P1 |
| 日次キャッシュ | `data/daily_cache.json` | `daily_cache.py` | P2（JSON blob 可） |
| セクターピア | `data/sector_peers.json` | `data_fetcher`, `daily_cache` | P2（マスタ） |
| DVC 銘柄出力 | `output/<ticker>.json` | `dvc_batch`, `dvc_phase1`, analyze API | P2（件数多・blob 検討） |
| アプリ設定 | `config.yaml` | `config_loader`, settings API | P3（任意） |

**DB に入れない:** `token.json`, `credentials.json` → ファイルまたは環境変数で管理（DB 化対象外）

**推奨フェーズ:** 設計 → Repository 層 → コアドメイン DB 実装 → API/バッチ切替 → マイグレーション → ファイル削除

---

### DB-1: データベース選定とスキーマ設計（ADR）

**Labels:** `enhancement`, `docs`

**ADR:** [`docs/ADR-001-database.md`](ADR-001-database.md)（SQLite 一本化・スキーマ・移行方針）

**エージェント可:** スキーマ草案、`docs/ADR-001-database.md`、ER 図  
**ユーザー判断:** SQLite のみか VPS で PostgreSQL か、ホスティング

**本文要点:**
- 単一ユーザー前提なら SQLite + SQLAlchemy で開始し、本番は PostgreSQL に寄せる案を比較
- テーブル案: `watchlist_items`, `portfolio_state`, `score_history`, `daily_reports`, `run_jobs`, `ticker_analyses`, `market_cache`, `app_settings`
- 論理日付・トランザクション（購入/売却）の整合要件を明記
- **本番移行:** 既存 JSON のフィールドを欠落なくマッピングする移行設計を ADR に含める（#15）

---

### DB-2: 永続化 Repository 層の導入（ファイル実装をラップ）

**Labels:** `enhancement`

**エージェント可:** ほぼ全て  
**依存:** DB-1

- `core/persistence/` に Protocol / 抽象インターフェース
- 既存 JSON 読み書きを `FileWatchlistRepository` 等に移し、挙動不変でテスト

---

### DB-3: ウォッチリスト・ポートフォリオ・取引を DB に移行

**Labels:** `enhancement`

**エージェント可:** 実装・テスト  
**ユーザー:** DB 接続文字列・初回 migrate 実行

- `watchlist_io` / `web/api` trade を Repository 経由に
- 購入加算・ロールバックを DB トランザクション化（ファイル Lock 不要に）

---

### DB-4: レポート・スコア履歴・バッチ状態を DB に移行

**Labels:** `enhancement`

**依存:** DB-3 推奨

- `last_report` / `previous_report` / `scores_history` / `run_status`
- `daily_routine`, `send_daily_report`, `get_report_merged` を更新

---

### DB-5: マーケットキャッシュ・DVC 出力・sector_peers を DB に移行

**Labels:** `enhancement`

- `daily_cache.json` → `market_cache` テーブル（JSON 列または正規化）
- `output/*.json` → `ticker_analyses`（ticker + logical_date + payload）
- 容量・インデックス方針を ADR に追記

---

### DB-6: 既存 JSON から DB へのマイグレーションスクリプトとファイル廃止

**Labels:** `enhancement`, `ops`  
**関連:** #15（本番データ移行）

**エージェント可:** `scripts/migrate_json_to_db.py`、ドキュメント  
**ユーザー:** 本番実行前バックアップ、VPS で一度実行

- ワンショット import + 検証（件数・checksum）
- **`--data-dir /opt/dpa_app`（本番パス）を指定して全 JSON を import**
- import 後: watchlist 銘柄数、現金残高、last_report の `data_date`、scores_history 最新日、output ファイル数をログ出力
- 読み書きパスを DB のみに切替後、旧 JSON は `.bak` へ退避
- ドライラン `--dry-run` で本番データを読みのみ検証可能にする

---

### DB-7: DB 移行後のテスト・OPERATIONS・ARCHITECTURE 更新

**Labels:** `tests`, `docs`

- `TestClient` / integration が in-memory DB（SQLite `:memory:`）を使用
- `docs/ARCHITECTURE.md`, `OPERATIONS.md` のパス記述を更新
- **`OPERATIONS.md` に本番 DB 切替手順**（バックアップ → migrate → 検証 → restart → ロールバック）を追記（#15）

---

### DB-8 / Issue #15: 本番（デプロイ済み）データの DB 移行（Epic 横断）

**Labels:** `enhancement`, `ops`  
**GitHub:** #15

**目的:** Mac の開発環境だけでなく、**ConoHa VPS 等にデプロイ済みの実データ**を DB 移行後も継続利用できるようにする。

**タスク**
- [x] 移行対象ファイル一覧の確定（Epic 表の全 JSON + `output/`）→ `OPERATIONS.md` DB-8 節
- [x] 本番バックアップ手順（`tar` / `cp -a data data.bak` 等）→ `OPERATIONS.md`
- [x] `migrate_json_to_db.py` / `migrate_production.sh` / `verify_db_migration.py` 本番手順
- [x] 移行後の整合チェックリスト（§6）・`verify_db_migration.py`（import 直後）
- [x] 失敗時ロールバック（§5）
- [x] Git 全同期との共存方針（コードは `git pull` のみ、data/output は VPS ローカル）
- [x] コード: `web/api.py` / `daily_routine.py` の watchlist・portfolio を `get_persistence` 経由に統一
- [ ] **本番 VPS 実施**（ユーザー: backup → migrate → verify → `DPA_PERSISTENCE=sqlite` → §6）

**受入条件**
- 本番 VPS の移行前後で、ダッシュボードの KPI・保有・レポートが実質同じ内容で表示される
- 手順どおりに別環境から再現可能（ドキュメント化）

**依存:** #8（設計）→ #13（スクリプト）→ 本 Issue で本番検証

---

## 企業分析 UI 拡張

### Issue #17: 登録銘柄一覧・分析詳細・日足チャート（企業分析タブ）

**GitHub:** [#17](https://github.com/kosei-doi/stock_v7/issues/17)

**要望**
- 既存の「企業分析＆自動追加」は維持
- **ウォッチリスト登録銘柄**を一覧表示し、タップで分析詳細へ
- 詳細に **日足チャート**（ローソク足）を表示

**現状**
- `templates/analyze.html` — 手入力 + `POST /api/analyze` のみ
- 分析結果は `output/<ticker>.json` に保存されるが、**OHLC 時系列は概要のみ**（`PriceHistoryOverview`）でチャート用データなし
- ウォッチリスト一覧は `/watchlist` ページのみ

**提案 UI**
```
[企業分析＆自動追加]（現行フォーム）
─────────────────────
[登録銘柄一覧]  コード | 銘柄名 | 状態 | Totalスコア | 終値
  → 行タップ
[詳細パネル / 別画面]
  - スコア・ファンダ・Z値（現行 result-detail 相当）
  - 日足チャート（直近 N 年、config.years に合わせる）
```

**バックエンド（案）**
| API | 役割 |
|-----|------|
| `GET /api/watchlist/analysis-index` | 一覧用: ticker, name, status, total_score, last_close, `has_output` |
| `GET /api/ticker/{ticker}/analysis` | `output/{ticker}.json` を返す（既存 analyze レスポンスと同形） |
| `GET /api/ticker/{ticker}/ohlc` | 日足 OHLCV（`fetch_price_history` またはキャッシュ）。初回は yfinance |

**フロント（案）**
- `analyze.html` に一覧 + 詳細（モバイルは下にスライド or `/analyze?ticker=`）
- チャート: **Lightweight Charts** または Chart.js（CDN、追加 npm なし）
- 分析 JSON が無い銘柄は「未分析」+「分析実行」ボタン

**タスク**
- [ ] OHLC API 実装（件数上限・日付昇順 JSON）
- [ ] 一覧 API + analyze ページ UI
- [ ] 詳細 + チャート描画
- [ ] 既存 `POST /api/analyze` 後に詳細へ遷移
- [ ] テスト: API スモーク、output 無し時 404

**受入条件**
- ウォッチリスト全銘柄が企業分析タブから一覧できる
- タップでスコア詳細と日足チャートが表示される
- 新規分析実行フローは従来どおり動作

**エージェント:** 実装可能（要: チャート用 OHLC API が新規）  
**依存:** なし（#16 円丸めとは独立）

---

## お金（円）の整数化

### Issue #16: 円建て金額を小数点以下なしに統一（丸め）

**GitHub:** [#16](https://github.com/kosei-doi/stock_v7/issues/16)

**背景:** 現状 `cash_yen`・`budget_used`・`avg_price`・売却代金などが `float` のまま保持・計算され、UI では `,.0f` 表示だが内部に小数が残る。

**方針（案）**
- 円建て**金額**は整数円に統一（`int` または保存直前に `round_yen()`）
- **対象:** `cash_yen`, `budget_used`, `cost`/`proceeds`, `avg_price`, `total_capital_yen`, `equity_value_yen`, `estimated_sale_cash`, `raw_available_budget`, `draft_budget_cap`, `available_budget`, `max_position_jpy` 等
- **対象外:** 株価（1株あたり・yfinance 由来）、比率（`target_cash_ratio`）、スコア、パーセント表示
- 共通関数例: `core/utils/money.py` の `yen_floor(x) -> int` — **切り捨て（`math.floor`）で確定**（四捨五入は使わない）

**主な変更箇所**
| 層 | ファイル |
|----|----------|
| 取引 API | `web/api.py`（purchase/sale/settings の cash・cost） |
| ウォッチリスト | `core/utils/watchlist_io.py`（avg_price 保存） |
| DPA | `dpa_draft.py`, `dpa_purge.py`, `daily_routine.py` |
| スキーマ | `dpa_schema.py`（Field 型を int 化するか、validator で丸め） |
| UI | `templates/trade.html`, `dashboard.html`（表示は既に整数寄り） |

**タスク**
- [ ] `yen_floor` ヘルパー追加（`math.floor`、円建て金額は切り捨て）
- [ ] 読み書き境界（JSON/将来 DB）で円を整数化
- [ ] 購入 `cost = shares * avg_price`、売却 `proceeds`、現金更新を整数円に
- [ ] テスト: `test_api_trade`, `test_watchlist_io`, `test_dpa_draft` で小数入力が整数に丸まること

**受入条件**
- ポートフォリオ現金・予算・取引後残高に小数が残らない
- 既存 pytest 全通過

**丸め方針（確定）:** 切り捨て（`math.floor`）。金額が負になる経路は現状なし前提。

**エージェント:** 実装・テストはほぼ可能

---

## 優先度 P3（任意改善）

### Issue 8: scoring の yfinance 重複呼び出し削減

**Labels:** `enhancement`

### Issue 9: 売却 API でユーザー指定価格・単元株チェックの Web/UI 整合

**Labels:** `enhancement`

### Issue 10: requirements-dev と本番 requirements の分離を CI に反映

**Labels:** `ops`, `tests`

---

## GitHub CLI で一括作成する例

```bash
cd "/Users/kosei/Library/CloudStorage/Box-Box/Personal/dev/stock_v7"

# Issue 1 はクローズ済み（再作成しない）
```

`gh label create` でラベルが無い場合は先に作成するか、`--label` を外す。

---

## 実装済み（Issue 不要・参照用）

- 保有株数の加算購入・加重平均（`watchlist_io`）
- ドラフト増分購入・論理日付統一・`--vi`・`run_status.json`
- API 認証・JSON アトミック書込・バッチ二重起動防止
- `.gitignore` 復元・OPERATIONS/deploy 方針統一
- 回帰テスト 13 件追加（計 54 passed）

詳細: コミット `0f1f2b0` / `docs/IMPLEMENTATION_PLAN.md`

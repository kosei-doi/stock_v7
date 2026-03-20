# データ構造とロジック 完全仕様書

本ドキュメントは、リファクタリング後のプロジェクトにおける**データ構造**と**ビジネスロジック**を漏れなく記述した仕様書です。

---

## 1. プロジェクト構成

### 1.1 ディレクトリ構造

```
stock_v7/
├── daily_routine.py      # 日次バッチのエントリポイント
├── send_daily_report.py  # Gmail 経由の日次レポート送信（cron 用）
├── config.yaml           # アプリ設定（単一ファイル）
├── requirements.txt
├── README.md
├── portfolio_state.json  # 現金残高（ルート。dpa.portfolio_path で変更可能）
│
├── data/                 # 永続化データ（JSON）の格納先
│   ├── watchlist.json    # ウォッチリスト＋保有（HOLDING は株数・平均単価を同梱）
│   ├── sector_peers.json
│   ├── daily_cache.json
│   ├── scores_history.json
│   ├── last_report.json  # 直近の日次レポート（DpaDailyReport）
│   ├── previous_report.json  # 前回実行分（data_date 変更時に退避）
│   └── run_status.json   # Web から起動する日次バッチの進行状況（任意）
│
├── web/                  # FastAPI + Jinja2 の Web UI（BFF）
│   ├── main.py           # ページルート・テンプレート
│   └── api.py            # /api/*（レポートマージ、分析、取引、設定など。専用のポートフォリオ画面・/api/positions/update は廃止）
│
├── core/
│   ├── dvc/              # DVC（Dynamic Value & Catalyst）関連
│   │   ├── dvc_phase1.py # 1銘柄用CLI
│   │   ├── dvc_batch.py  # ウォッチリスト一括DVC
│   │   ├── scoring.py    # スコア計算の中心
│   │   ├── schema.py     # DVC 出力の Pydantic モデル
│   │   ├── indicators.py # テクニカル・ファンダ指標
│   │   ├── data_fetcher.py
│   │   └── ai_agent.py   # LLM 要約（オプション）
│   │
│   ├── dpa/              # DPA（Dynamic Portfolio Architect）関連
│   │   ├── dpa_macro.py       # マクロ判定・目標現金比率（MAX_POSITION_* も定義）
│   │   ├── dpa_scores.py      # スコア履歴の読書・トレンド
│   │   ├── dpa_portfolio_score.py  # ポートフォリオ用 total_score
│   │   ├── dpa_weights.py     # ターゲット構成比
│   │   ├── dpa_purge.py       # 売却候補の判定
│   │   ├── dpa_draft.py       # 購入候補の判定
│   │   └── dpa_schema.py      # DPA の Pydantic モデル
│   │
│   └── utils/            # 共通ユーティリティ
│       ├── config_loader.py  # 設定読込・型検証
│       ├── daily_cache.py    # マクロ・ピアの日次キャッシュ
│       ├── watchlist_io.py   # ウォッチリスト・HOLDING I/O
│       └── io_utils.py       # DVC 出力 JSON 保存など
│
├── output/               # 銘柄ごとの DVC 出力（output/<ticker>.json）
├── scripts/              # デプロイ用（例: systemd サービス）
├── tests/
└── docs/
```

**注**: 旧来の `data/positions.json` は廃止。保有株数・平均単価は `watchlist.json` の `HOLDING` 行に保持し、`positions_from_watchlist()` が `{ ticker: { shares, avg_price? } }` 形式に変換する。

### 1.2 デフォルトパス一覧

| 用途 | デフォルトパス | 設定キー（例） |
|------|----------------|----------------|
| ウォッチリスト（保有含む） | `data/watchlist.json` | CLI `--watchlist` または `watchlist` 相当 |
| ウォッチリスト上限 | 30 件（既定） | `watchlist.max_items` → `get_validated_config` で `watchlist_max_items`。**設定画面の値は `config.yaml` に保存される。Web の企業分析・ウォッチ追加 API と日次バッチ（`--config` 未指定時はプロジェクト直下の `config.yaml` があれば読込）で同じファイルを参照する。** |
| ポートフォリオ状態（現金） | `portfolio_state.json` | `dpa.portfolio_path` |
| セクター・ピア | `data/sector_peers.json` | `dpa.sector_peers_path` |
| 日次キャッシュ | `data/daily_cache.json` | `cache.cache_path` または `dpa.cache_path` |
| スコア履歴 | `data/scores_history.json` | `dpa.scores_history_path` |
| 最終レポート | `data/last_report.json` | `daily_routine.main` 内で固定 |
| 前回レポート | `data/previous_report.json` | 同上（`data_date` が変わるとき前回を退避） |
| バッチ進捗 | `data/run_status.json` | Web API が書き込み |
| DVC 出力 | `output/<ticker>.json` | `output_dir` |

---

## 2. データファイルの構造

### 2.1 data/watchlist.json

**役割**: 監視・保有対象銘柄の一覧（Single Source of Truth）。最大件数は `watchlist.max_items`（既定 30）。`status` で HOLDING / WATCHING を区別。

**形式**: JSON 配列。各要素はオブジェクト。

| キー | 型 | 必須 | 説明 |
|------|-----|------|------|
| `ticker` | string | 実質必須 | 銘柄コード（例: `"7203.T"`） |
| `ticker_symbol` | string | 任意 | `ticker` の別名（互換用） |
| `status` | string | 任意 | `"HOLDING"` または `"WATCHING"`。省略時は WATCHING |

**ルール**:
- `status === "HOLDING"` の銘柄は、ウォッチリスト上限超過時の自動削除対象外。
- 追加時に上限を超える場合は、WATCHING のうちスコア最下位を 1 件削除してから追加する（`watchlist.max_items`、既定 30）。

**HOLDING 行の追加フィールド**:

| キー | 型 | 説明 |
|------|-----|------|
| `shares` または `shares_held` | number | 保有株数 |
| `avg_price` | number | 任意。平均取得単価（円） |

**例**:
```json
[
  { "ticker": "3197.T", "status": "WATCHING" },
  { "ticker": "4765.T", "status": "HOLDING", "shares": 100, "avg_price": 580.0 }
]
```

日次バッチ・Web の取引 API は `positions_from_watchlist()` で上記を `{ "4765.T": { "shares": 100, "avg_price": 580.0 } }` 形式に読み替える。

---

### 2.2 data/sector_peers.json

**役割**: セクター名 → 代表銘柄ティッカーリストのマッピング。DVC の「空間軸 Z スコア」（ピア比較）で使用。

**形式**: JSON オブジェクト。`{ "セクター名": ["ticker1", "ticker2", ...], ... }`

- キー: セクター名（yfinance の `sector` や、それに近い文字列）。
- 値: そのセクターの代表銘柄のティッカー配列。

**参照ロジック**（`data_fetcher.get_sector_peers`）:
- 銘柄の `sector` がキーと完全一致すればそのリストを返す。
- しなければ「キーに sector が含まれる」「sector にキーが含まれる」の部分一致でフォールバック。

**例**:
```json
{
  "Communication Services": ["9432.T", "9433.T"],
  "Technology": ["6501.T", "6758.T", "8035.T"]
}
```

---

### 2.3 data/daily_cache.json

**役割**: ベンチマーク株価履歴・代表銘柄の簡易情報・VI 履歴をキャッシュし、同日中の再取得を避ける。

**形式**: 単一の JSON オブジェクト。

| キー | 型 | 説明 |
|------|-----|------|
| `updated_date` | string | キャッシュを更新した日（ISO 日付 `YYYY-MM-DD`）。JST の「今日」で更新される。 |
| `benchmark_ticker` | string | ベンチマークのティッカー（例: `"1306.T"`） |
| `years` | number | 取得年数（例: `5`） |
| `benchmark_history` | object | pandas DataFrame を `orient="split"` で JSON 化したもの（`columns`, `index`, `data`） |
| `peers_data` | object | `{ "ticker": { "currentPrice", "bookValue", "trailingEps" }, ... }`。代表銘柄のスナップショット。 |
| `vi_ticker` | string or null | VI 用ティッカー（例: `"^VIX"`）。未使用なら null。 |
| `vi_history` | object or null | VI の日足を `orient="split"` で JSON 化したもの。`vi_ticker` 指定時のみ存在。 |

**fresh 判定**（`daily_cache.cache_is_fresh`）:
- `benchmark_ticker` / `years` / `vi_ticker` が今回のリクエストと一致することは必須。
- **now を渡す場合**（日次バッチから呼ぶ場合）:
  - 週末: `updated_date` が直近金曜以降なら fresh。
  - 平日・カットオフ（デフォルト 6:00 JST）前: `updated_date` が直近営業日以降なら fresh。
  - 平日・カットオフ後: `updated_date` が今日なら fresh。
- **now を渡さない場合**: `updated_date === 今日(JST)` なら fresh。

**書き込み条件**: ベンチマーク取得結果（`bench_df`）が空でないときのみキャッシュを上書きする。空の場合は書き込まず、次回 fresh でないとみなして再取得される。

---

### 2.4 data/scores_history.json

**役割**: 日付別の銘柄スコア履歴。スコアトレンド（短期・長期）の計算に使用。

**形式**: JSON オブジェクト。`{ "YYYY-MM-DD": { "ticker": { "total", "value", "safety", "momentum" }, ... }, ... }`

- トップキー: 日付（JST の「バッチ実行日」の ISO 文字列）。
- 各日付の値: 銘柄コードをキー、スコアを値とするオブジェクト。
- 各銘柄の値: `total`（総合）, `value`, `safety`, `momentum`（いずれも number）。

**日付の意味**: キーになっている日付は「その日にバッチを実行した」日であり、株価の最終取引日ではない。

**例**:
```json
{
  "2026-03-10": {
    "7203.T": { "total": 63.1, "value": 55.0, "safety": 70.0, "momentum": 58.0 }
  }
}
```

---

### 2.5 data/last_report.json

**役割**: 直近の日次バッチで生成した `DpaDailyReport` をそのまま JSON 化したもの。Web 表示や外部連携用。

**形式**: `DpaDailyReport` の Pydantic モデルを `model_dump(mode="json")` した 1 オブジェクト。フィールドは後述の「DPA スキーマ」を参照。

---

### 2.6 data/previous_report.json

**役割**: 1 つ前の `last_report.json` のスナップショット。`daily_routine.main` が `last_report.json` を上書きする直前に、既存ファイルの `data_date` が今回と異なる場合のみ退避する。Web のレポート画面で順位変化などの比較に利用。

**形式**: `last_report.json` と同じスキーマの JSON オブジェクト。

---

### 2.7 portfolio_state.json（ルート）

**役割**: 現金残高など、ポートフォリオの状態を保持。

**形式**: JSON オブジェクト。

| キー | 型 | 説明 |
|------|-----|------|
| `cash_yen` | number | 現金残高（円）。存在しない場合はコード側で `DEFAULT_TOTAL_CAPITAL_JPY`（500万）を使用。 |

---

### 2.8 output/<ticker>.json

**役割**: 銘柄ごとの DVC 実行結果。`DvcScoreOutput` を JSON 化したもの。

**形式**: 後述の「DVC スキーマ（DvcScoreOutput）」に準拠。

---

## 3. 設定（config.yaml / config_loader）

### 3.1 設定の読み込み

- **単一ファイル**: プロジェクト直下の **`config.yaml` のみ**（`config_example.yaml` は廃止）。  
- **config_loader.load_merged_config(config_path=None)**  
  - `config_path` が `None`: プロジェクトの `config.yaml` があれば読む（無ければ空 dict）。  
  - 明示パス: CLI の `--config` 用にそのファイルだけを読む。  
- **config_loader.load_config**  
  - 上記と同様に **1 ファイルをそのまま**読み込む（ファイル同士のマージは行わない）。  
  - `config_path` が `None` かつ `default_to_project_yaml=False` のときは `{}`。  
- **欠損キー**: YAML に書かれていない項目は **`get_validated_config`** がコード上のデフォルトで補完する。  
- **Web API** の検証済み設定: `get_validated_config(load_merged_config(None))`。  
- **config_loader.get_validated_config(cfg)**  
  - 生の dict を型変換・デフォルト補完した **フラットな dict** に変換する。  
  - **ネスト YAML**（`dpa:`, `cache:`, `llm:`, `watchlist:`）は `get_validated_config` 内で読み取り、出力では `benchmark_ticker`, `cache_path`, `mu_cash`, `watchlist_max_items` などのフラットキーに統一する。  
  - 空文字の `vi_ticker` は `None` に正規化。

### 3.2 config.yaml の構造（概要）

| ブロック | 内容 |
|----------|------|
| トップレベル | `benchmark_ticker`, `years`, `output_dir` など |
| `llm:` | `enabled`, `provider`, `model` |
| `cache:`（任意） | `cache_path`, `cutoff_hour`, `cutoff_minute`, `market_tz` |
| `dpa:` | `vi_ticker`, `mu_cash`, `a_vi`, `b_macd`, `portfolio_path`, `sector_peers_path`, `scores_history_path`, ほか任意 |
| `watchlist:` | `max_items`（既定 30） |
| `daily_report:` | `enabled`（メール送信のオンオフ） |

### 3.3 設定キーとデフォルト値（get_validated_config 出力）

| キー | 型 | デフォルト | 説明 |
|------|-----|------------|------|
| `benchmark_ticker` | str | `"1306.T"` | ベンチマークティッカー |
| `years` | int | `5` | 過去データ取得年数 |
| `output_dir` | str | `"output"` | DVC 出力ディレクトリ |
| `cache_path` | str | `"data/daily_cache.json"` | 日次キャッシュファイル |
| `cache_cutoff_hour` | int | `6` | キャッシュ「今日」判定の時刻（時）JST |
| `cache_cutoff_minute` | int | `0` | 同上（分） |
| `market_tz` | str | `"Asia/Tokyo"` | 市場タイムゾーン |
| `llm_enabled` | bool | `false` | LLM でカタリスト要約を生成するか |
| `llm_model` | str | `"gpt-4.1-mini"` | OpenAI モデル名 |
| `total_capital_jpy` | float | `5000000` | フォールバック用総資金（円）。実運用では総資産は現金＋評価額で算出 |
| `portfolio_path` | str | `"portfolio_state.json"` | ポートフォリオ状態ファイル（現金） |
| `watchlist_max_items` | int | `30` | ウォッチリスト上限（`watchlist.max_items`） |
| `sector_peers_path` | str | `"data/sector_peers.json"` | セクター・ピアファイル |
| `scores_history_path` | str | `"data/scores_history.json"` | スコア履歴ファイル |
| `vi_ticker` | str or None | 設定次第 | VI 用ティッカー（例: `"^VIX"`） |
| `mu_cash` | float | `0.4` | 目標現金比率のベースライン |
| `a_vi` | float | `0.1` | VI Z スコアの係数（恐怖で現金増） |
| `b_macd` | float | `0.1` | MACD トレンドの係数（上向きで現金減） |
| `macd_scale` | float | `0.002` | MACD トレンドを -1〜+1 に正規化するスケール |
| `min_cash_ratio` | float | `0.2` | 目標現金比率の下限 |
| `max_cash_ratio` | float | `0.8` | 目標現金比率の上限 |
| `momentum_threshold` | float | `50.0` | 購入「着火点」モメンタムスコア閾値 |
| `lot_size` | int | `100` | 売買単位（株数） |

---

## 4. DVC（Dynamic Value & Catalyst）ロジック

### 4.1 実行フロー（1銘柄: run_dvc_for_ticker）

1. **データ取得**
   - 対象銘柄: `data_fetcher.fetch_price_history(ticker, years)` で株価（日足）を取得。列名は `normalize_price_columns` で小文字化（open, high, low, close, volume 等）。
   - ベンチマーク: 呼び出し元から `bench_df` が渡されていればそれを使用。なければ `fetch_benchmark_history` で取得。
   - ファンダメンタル: `fetch_fundamentals(ticker)` で yfinance の info から `FundamentalSnapshot`（発行済み株数・BPS・EPS・セクター・銘柄名）を取得。
   - ピア: `fetch_sector_peers_map(sector_peers_path)` でセクター→ティッカーリストを取得し、銘柄の sector で `get_sector_peers` して代表銘柄リストを解決。ピアの currentPrice/bookValue/trailingEps はキャッシュ（peers_data）があればそれを使用、なければ yfinance で取得。

2. **Value 指標**
   - **時間軸 Z スコア**: 銘柄の過去の PB/PE 系列から `compute_value_time_zscores` で `time_z_pb`, `time_z_pe`（直近が履歴のどこにあるか）。
   - **空間軸 Z スコア**: 銘柄の現在 PB/PE とピアの PB/PE リストから `compute_value_space_zscores` で `space_z_pb`, `space_z_pe`。
   - Z を 0〜100 点にマッピング（`_map_z_to_score`。z=0→50点、|z|=2 付近→10/90 点）。time は 0.5:0.5、space は 0.5:0.5 で結合し、さらに time:space = 0.6:0.4 で結合して **value_score**。

3. **Safety 指標**
   - 簡易 F スコア: `_compute_simple_f_score(ticker)`（ROA>0, 営業CF>0, レバレッジ, 流動比率, 粗利率など 0〜9 点スケール）。
   - 簡易 Altman Z: `_compute_simple_altman_z(ticker, price_df, fundamentals)`。
   - **safety_score**: F スコアを 0〜100 に正規化（×100/9）で 0.7、Altman Z を 1.8 基準で Z 化して 0〜100 にマッピングしたものを 0.3 で加重平均。

4. **Momentum 指標**
   - MACD ゴールデンクロス: `detect_macd_cross(price_df)` で「直近クロスから何日か」「クロス時の傾き」を取得。
   - 出来高 Z スコア: `compute_volume_zscore(price_df)`。
   - **momentum_score**: クロス鮮度を指数減衰（time_scale=10）で 0〜100 にし 0.5、出来高 Z を 0〜100 にし 0.5 で結合。

5. **Market & Risk**
   - ベータ・R²・α: `compute_beta_and_r2(price_df, bench_df)`（リターン同士の線形回帰）。
   - ATR%: `compute_atr_percent(price_df)`（14 日 ATR / 直近終値 × 100）。

6. **総合スコア**
   - **total_score** = value 0.4 + safety 0.4 + momentum 0.2（`_combine_scores`。None の成分は除外して残りで正規化）。

7. **LLM（オプション）**
   - `llm_enabled` が真のとき、`ai_agent.generate_ai_analysis` でカタリスト要約・損切り推奨・警告フラグを取得。偽のときは定型の `AiAnalysis` を返す。

8. **出力**
   - `DvcScoreOutput`（ticker, name, sector, scores, market_linkage, risk_metrics, ai_analysis, data_overview）を返す。`dvc_batch` ではこれを `output/<ticker>.json` に保存し、`scores_history` にその日の total/value/safety/momentum を追記する。

### 4.2 一括実行（run_dvc_for_watchlist）

- `watchlist` を読み、銘柄リストを取得。
- `get_macro_and_peers_data` でベンチマーク・ピア・VI を 1 回だけ取得（キャッシュ fresh ならキャッシュから）。
- 各銘柄に対して `run_dvc_for_ticker` を実行（bench_df と peers_data を共通で渡す）。
- 結果を `output/<ticker>.json` に保存し、`update_scores_history_for_date(today_key, results, path=scores_history_path)` でスコア履歴を更新。`today_key` は JST の「今日」の ISO 日付。

---

## 5. DPA（Dynamic Portfolio Architect）ロジック

### 5.1 マクロ判定（dpa_macro.get_macro_state）

- **VI Z スコア**: `compute_vi_z(vi_series, window=60)`。直近の VI が過去 60 日の分布のどこにあるかを Z スコアで算出。
- **MACD トレンド**: `compute_macd_trend(bench_df, window=5, scale=0.002)`。ベンチマークの MACD とシグナルの差（spread）の直近トレンドを -1〜+1 に正規化。
- **目標現金比率（連続）**:  
  `cash = mu_cash + a_vi * max(vi_z, 0) - b_macd * macd_trend`  
  を `min_cash_ratio`〜`max_cash_ratio` にクリップ。
- **フェーズラベル（後付け）**:  
  - cash ≤ 0.3 → CRUISE（巡航）  
  - cash ≤ 0.5 → CAUTION（警戒）  
  - cash ≥ 0.7 → PANIC（パニック）  
  - それ以外 → REVERSAL（反転狙撃）

### 5.2 スコアトレンド（dpa_scores.compute_score_trend）

- `scores_history` からその銘柄の `total` の時系列を日付順に取得。
- **last**: 直近の total 値。
- **level**: last を 0〜100 想定で 0〜1 に正規化（/100 して 0〜1 にクリップ）。
- **trend**: 短期（5日）と中期（20日）の移動平均の差を 20 で割り、-1〜+1 にクリップ。

### 5.3 ポートフォリオ用 total_score（dpa_portfolio_score.compute_portfolio_total_score）

- ベースは DVC の `total_score`（0〜100 想定）。
- マクロの防御度: `(target_cash_ratio - 0.4) / 0.4` を 0〜1 にクリップ（`get_defense_intensity`）。
- β, R², α, ATR% で加減:
  - 防御が強いとき: 高β・高R²の減点を強く、ATR 減点を強く、α 加点は控えめ。
  - 防御が弱いとき: β・R²の減点は弱く、α をやや強く加点。ATR は常にやや減点。
- 最終スコアは 0〜150 にクリップ（ソート・購入順に使用）。

### 5.4 ターゲット構成比（dpa_weights.compute_target_weights）

- 非現金部分: `non_cash = 1 - target_cash_ratio`（0〜1 にクリップ）。
- 銘柄ごとに `raw_i = 0.7 * level_i + 0.3 * trend_i` のベースを計算（level はポートフォリオスコアの 0〜1 正規化、または score_trends の level）。
- リスク調整: β（1 超でペナルティ）、R²（高いほど防御時にペナルティ）、ATR%（高いほどペナルティ）、α（プラスならボーナス）で `risk_factor` を掛ける。防御度が高いほど β・R² のペナルティが強い。
- `raw[ticker] = base_raw * risk_factor` を 0.5〜1.5 にクリップした factor で掛け、**正規化の母集団上の** raw を合計で正規化し、`target_weights[ticker] = non_cash * (raw[ticker] / total_raw)`。
- **日次バッチ（`daily_routine`）**では `allocation_tickers` に**保有銘柄のティッカー集合**を渡す。すなわち **保有銘柄のみ**で raw を正規化し、その合計が `non_cash` になる（ウォッチの未保有銘柄は `target_weights = 0`）。ドラフトの仮想組入では、仮想ポートフォリオに含まれる銘柄だけを `dvc_subset` に入れて同関数を呼ぶため、従来どおりその集合内だけで `non_cash` を分割する。

### 5.5 パージ（dpa_purge.run_purge）

- 保有銘柄（holdings）のみ対象。
- `target_weights` は上記のとおり **保有銘柄のみで正規化した**総資産ベースの目標比率（各ティッカーの割合は 0〜1、**保有分の合計**は `1 - target_cash_ratio`。未保有のウォッチ銘柄は 0）。
- 各保有銘柄について `w = current_weights[ticker]`（総資産に対する現在比率）、`w_star = target_weights[ticker]`（同じく総資産ベースの目標比率）、`over = max(0, w - w_star)`。  
  `over > over_weight_threshold`（デフォルト 0.02 = 2%pt）のとき売却候補に追加。
- 理由: フェーズが PANIC なら `MACRO_PANIC`、それ以外は `SCORE_DECAY`。日本語理由文を付与。

### 5.6 ドラフト（dpa_draft.run_draft） ― 仮想組入 & 動的N最適化

- **空き予算**: `raw_available_budget = max(0, cash_current - total_capital_actual * target_cash_ratio)`。  
  パニック時またはこれが非正のときは `available_budget = 0`、`recommendations = []` で返す（raw は保持）。
- **対象**: ウォッチリストの **WATCHING** の銘柄で、`momentum_score >= momentum_threshold`（デフォルト 50）のもの。**保有済み銘柄も候補に含まれる**（追加買いのシミュレーション対象）。
- **候補ソート**: 上記候補について、`portfolio_scores`（なければ `compute_portfolio_total_score`）を使って**ポートフォリオ用 total_score 降順**に並べる。
- **仮想組入（Simulated Inclusion）**:
  - N を 1〜`MAX_DRAFT_CANDIDATES`（デフォルト 5、候補数がそれ以下なら候補数まで）でループ。
  - 各 N について、**上位 N 銘柄を既存保有銘柄に加えた「仮想ポートフォリオ」**を作る。
  - その仮想ポートフォリオに対して `compute_target_weights` を呼び、**仮想ターゲット構成比 `simulated_weights`** を計算する（score_trends・portfolio_scores は仮想ポートフォリオに限定したサブセットで渡す）。
- **シナリオごとの買付シミュレーション**:
  - `scenario_budget = available_budget` を初期化し、上位 N 候補を順に見ていく。
  - 各銘柄について `w = simulated_weights[ticker]` から `target_jpy = total_capital_actual * w` を計算。
  - 1銘柄上限 `max_pos_value = min(MAX_POSITION_PCT * total_capital_actual, MAX_POSITION_JPY)` で `target_jpy = min(target_jpy, max_pos_value)` としてクリップ。
  - `lot_cost = price * lot_size` をもとに  
    `max_lots_by_target = floor(target_jpy / lot_cost)`、`max_lots_by_budget = floor(scenario_budget / lot_cost)` を計算し、  
    `lots = min(max_lots_by_target, max_lots_by_budget)` ロットだけ購入（0以下ならスキップ）。
  - 実際に `shares = lots * lot_size`、`cost = shares * price` を使い、`scenario_budget -= cost`。  
    `BuyRecommendation(ticker, name, shares, limit_price=None, score=portfolio_score, budget_used=cost)` を `scenario_buys` に追加。
- **シナリオ評価（Dynamic N-Optimization）**:
  - `scenario_buys` が空なら `scenario_score = 0`。
  - そうでなければ  
    - `total_spent = available_budget - scenario_budget`  
    - `utilization = total_spent / available_budget`（予算消化率）  
    - `count = len(scenario_buys)`（分散銘柄数）  
    - `weighted_score = Σ( score_i * budget_used_i ) / total_spent`（購入金額で重み付けした平均スコア）  
    - 評価式:  
      \[
      scenario\_score = weighted\_score \times (1 + 0.1 \times count) \times utilization
      \]
      （0.1 は分散ボーナス係数）
- **最適シナリオの採用**:
  - N=1〜`MAX_DRAFT_CANDIDATES` の中で `scenario_score` が最大のシナリオを採用。
  - そのシナリオの `scenario_buys` を `DpaDraftOutput.recommendations` に、  
    `available_budget - scenario_budget`（消費額）を `DpaDraftOutput.available_budget` に反映する。
  - `recommendations` は最終的に **score 降順でソート**して返す。

---

## 6. 日次バッチの流れ（daily_routine.run_daily_routine）

1. **ステップ1**: ウォッチリスト読込・企業分析（DVC）  
   `run_dvc_for_watchlist` で全銘柄の DVC を実行。キャッシュからマクロ・ピアを読むか API 取得。結果を `output/<ticker>.json` に保存し、`scores_history` を更新。

2. **ステップ2**: ウォッチリスト・現金の読込  
   `watchlist` と `portfolio_state` を読み、`positions_from_watchlist` で HOLDING の株数・単価を取得。DVC 結果から直近終値を取り `current_prices` を構築。`holdings` と現在構成比・総資産を計算。

3. **ステップ3**: マクロ判定  
   `get_macro_and_peers_data` で bench_df, vi_series を取得し、`get_macro_state` で目標現金比率とフェーズを算出。

4. **ステップ4**: スコアトレンド・ポートフォリオスコア・ターゲット構成比  
   `load_scores_history` → 銘柄ごとに `compute_score_trend`。全銘柄に `compute_portfolio_total_score` を適用し、`compute_target_weights` でターゲット構成比を算出。

5. **ステップ5**: パージ  
   `run_purge` で売却候補を算出。

6. **ステップ6**: ドラフト  
   WATCHING の銘柄（保有・未保有を問わず、着火点を満たすもの）を対象に、仮想組入＋動的N最適化を行う `run_draft` で購入候補を算出。

7. **ステップ7**: レポート生成・保存  
   `DpaDailyReport` を組み立て、`format_report` でテキスト化。  
   `main()` 側で、既存 `last_report.json` の `data_date` が今回と異なる場合は `data/previous_report.json` に退避してから `data/last_report.json` を上書き保存し、テキストを stdout に出力。

---

## 7. 型・スキーマ一覧

### 7.1 DVC（core.dvc.schema）

- **PriceHistoryOverview**: rows, date_min, date_max, columns, last_close, empty  
- **FundamentalsOverview**: shares_outstanding, book_value_per_share, eps_ttm, sector, long_name  
- **SectorPeersOverview**: resolved_sector, peer_count, peer_tickers, peer_pb_count, peer_pe_count  
- **DataOverview**: price_history, benchmark, fundamentals, sector_peers, value_inputs  
- **Scores**: value_score, safety_score, momentum_score, total_score（いずれも Optional[float]）  
- **MarketLinkage**: benchmark, beta, r_squared, alpha  
- **RiskMetrics**: atr_percent  
- **AiAnalysis**: catalyst_summary, stop_loss_recommendation, warning_flag  
- **DvcScoreOutput**: ticker, name, sector, scores, market_linkage, risk_metrics, ai_analysis, data_overview  

### 7.2 DPA（core.dpa.dpa_schema）

- **MacroPhase**: 列挙 CRUISE, CAUTION, PANIC, REVERSAL  
- **MacroState**: phase, phase_name_ja, target_cash_ratio, vi_z, macd_trend  
- **SellReason**: 列挙 MACRO_PANIC, SCORE_DECAY（目標比率超過の売却理由）  
- **PurgeItem**: ticker, reason, reason_ja, current_price, stop_loss_price, score  
- **DpaPurgeOutput**: phase, items, total_count  
- **BuyRecommendation**: ticker, name, shares, limit_price, score, budget_used  
- **DpaDraftOutput**: phase, available_budget, raw_available_budget, recommendations  
- **DpaDailyReport**: `created_at`, `data_date`, `target_cash_ratio`, `phase`, `phase_name_ja`, `vi_z`, `macd_trend`, `cash_yen`, `total_capital_yen`, `equity_value_yen`, `ticker_names`, `last_prices`, `current_weights`, `target_weights`, `score_trends`, `portfolio_scores`, `purge`, `draft`, `report_text`

### 7.3 その他（TypedDict / dataclass）

- **WatchlistItem**（watchlist_io）: ticker, ticker_symbol?, status?  
- **PositionEntry**（watchlist_io）: shares?, shares_held?, avg_price?  
- **FundamentalSnapshot**（data_fetcher）: shares_outstanding, book_value_per_share, eps_ttm, sector, long_name  
- **ValueSignals**（indicators）: time_z_pb, time_z_pe, space_z_pb, space_z_pe  
- **SafetySignals**: f_score, altman_z  
- **MomentumSignals**: macd_cross_recent_days, macd_slope_at_cross, volume_z  
- **MarketRiskSignals**: beta, r_squared, alpha, atr_percent  

---

## 8. 定数・ビジネスルールまとめ

| 項目 | 値 | 所在 |
|------|-----|------|
| ウォッチリスト上限 | 既定 30 件（`config.yaml` の `watchlist.max_items`） | `get_validated_config` の `watchlist_max_items`、API から `watchlist_io` に `max_items` として渡す。コード定数 `watchlist_io.MAX_WATCHLIST` は未指定時のフォールバック |
| HOLDING / WATCHING | 文字列で比較、省略時 WATCHING | watchlist_io |
| キャッシュ fresh のカットオフ | 6:00 JST（設定可能） | daily_cache.DEFAULT_CACHE_CUTOFF_* |
| スコアトレンド短期・長期 | 5 日・20 日 | dpa_scores.compute_score_trend |
| 総合スコアの重み | value 0.4, safety 0.4, momentum 0.2 | scoring._combine_scores |
| 目標現金比率の式 | mu_cash + a_vi*max(vi_z,0) - b_macd*macd_trend、0.2〜0.8 にクリップ | dpa_macro._continuous_cash_ratio |
| フェーズ境界 | ≤0.3 CRUISE, ≤0.5 CAUTION, ≥0.7 PANIC, それ以外 REVERSAL | dpa_macro._phase_from_cash |
| 1 銘柄上限（ドラフト購入シミュレーション） | 15% または 75 万円の小さい方 | `dpa_macro.MAX_POSITION_PCT` / `MAX_POSITION_JPY`（`dpa_draft` で参照） |
| パージのオーバー閾値 | 2%（0.02） | dpa_purge.run_purge |
| 着火点モメンタム | 50.0 | dpa_draft.DEFAULT_IGNITION_MOMENTUM_THRESHOLD |
| 売買単位 | 100 株 | dpa_draft.LOT_SIZE |
| 動的Nシミュレーションの最大候補数 | 5 銘柄 | dpa_draft.MAX_DRAFT_CANDIDATES |
| ターゲット重みの level/trend 係数 | alpha_level=0.7, beta_trend=0.3 | dpa_weights.compute_target_weights |

---

以上が、現在のデータ構造とロジックの完全な記述です。実装と乖離がある場合は実装を正とし、本ドキュメントを更新してください。

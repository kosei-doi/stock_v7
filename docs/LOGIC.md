# ロジック仕様（DVC + DPA 実装準拠）

このファイルは、`daily_routine.py` と `core/*` の現行実装に合わせたロジック仕様の正本です。

## 1. 全体設計ルール

- 単一設定ソースは `config.yaml`（`core/utils/config_loader.py` で型補正・既定値補完）
- 保有情報の SoT は `data/watchlist.json`（`status=HOLDING` に `shares` / `avg_price` を持つ）
- 日次意思決定は `daily_routine.py` が一括実行
- 売買は日本株単元株前提（既定 `lot_size=100`）
- 比率計算は「総資産の実値（現金 + 株式評価額）」ベース

## 2. 設定解決ロジック

`get_validated_config()` は以下を実行します。

- 文字列・数値の型変換（失敗時は既定値）
- `watchlist.max_items` が `null` / 不正型でも `watchlist_max_items_from_raw_config()` で救済
- `dpa.ignition_momentum_threshold` を優先、なければ `dpa.momentum_threshold` を後方互換で利用
- `vi_ticker` は空文字を `None` に正規化
- `purge_lot_threshold` は `dpa.purge_lot_threshold` を採用（既定 0.5）

## 3. 日次バッチ（`run_daily_routine`）

実行順は次のとおりです。

1. `run_dvc_for_watchlist()` でウォッチリスト全銘柄を再分析し、`output/<ticker>.json` 更新
2. 同時に `scores_history.json` に当日分を追記
3. `watchlist` / `portfolio_state` から保有・現金を復元し、現在価格で評価額を再計算
4. `get_macro_state()` で `vi_z` / `macd_trend` / `target_cash_ratio` を算出
5. 銘柄ごとに `compute_score_trend()`（線形回帰 + 不足分タイムマシン補完）
6. `compute_portfolio_total_score()` で DVC スコアをポートフォリオ観点へ補正
7. `compute_target_weights()` で非現金枠の目標比率を計算
8. `run_purge()` で売却候補を生成（非対称丸め）
9. `run_draft()` で購入候補を生成（動的 N 最適化）
10. `DpaDailyReport` を構築し `data/last_report.json` 保存（異日なら旧 `last` を `previous` へ退避）

補足:

- `data_date` は JST 6:00 区切り（`now - 6h` の日付）
- `total_capital_jpy` 設定値は最終意思決定では使わず、実資産値を使う

## 4. DVC スコア計算（`core/dvc/scoring.py`）

### 4.1 Value

- 時系列割安度:
  - `pb_series = close / bps`, `pe_series = close / eps`
  - 各系列の Z スコア（全期間平均・標準偏差）
- セクター内相対割安度:
  - ピア群 PB/PE に対する `target_pb`, `target_pe` の Z スコア
- Z スコアを 0-100 に線形変換:
  - `score = 50 - 20*z`（`low_is_good=True`）
- 合成:
  - `value_time = mean(pb_score, pe_score)`
  - `value_space = mean(pb_score, pe_score)`
  - `value_score = 0.6*time + 0.4*space`

### 4.2 Safety

- F-score 近似（`yfinance.info` のスナップショット情報）
- Altman Z 近似（必要項目不足時は `None`）
- 合成:
  - `safety_score = 0.7*f_score_norm + 0.3*altman_score`

### 4.3 Momentum

- MACD GC 鮮度:
  - `spread = macd - signal` の負→正クロス最終点からの日数 `d`
  - `macd_score = 100 * exp(-d/10)`
- 出来高:
  - 20 日窓の出来高 Z スコアを `low_is_good=False` で 0-100 化
- 合成:
  - `momentum_score = mean(macd_score, volume_score)`

### 4.4 Market/Risk

- `beta`, `r_squared`, `alpha`: 日次リターン回帰（最低 30 点）
- `atr_percent`: ATR/終値 * 100

### 4.5 総合

- `total_score = 0.4*value + 0.4*safety + 0.2*momentum`
- 出力は `DvcScoreOutput`（`data_overview` 含む）

## 5. マクロ判定（`core/dpa/dpa_macro.py`）

### 5.1 VI Z スコア

- 既定 `window=60`
- `vi_z = (recent - mean(hist)) / std(hist)`（`std=0` 等は `None`）

### 5.2 MACD トレンド（Z スコア方式）

- `spread = macd - signal`
- `spread_ma = rolling_mean(spread, 5)`
- 60 日ローリングで `z = (spread_ma - mean) / (std + 1e-8)`
- `z_last` を `[-3, +3]` にクリップ
- `macd_trend = z_last / 3.0`（`[-1, +1]`）
- データ不足時は `None`

### 5.3 目標現金比率

- `cash = mu_cash + a_vi*max(vi_z, 0) - b_macd*macd_trend`
- `cash` を `[min_cash_ratio, max_cash_ratio]` にクリップ
- フェーズは `cash` から後付けラベル:
  - `<=0.3`: `CRUISE`
  - `<=0.5`: `CAUTION`
  - `>=0.7`: `PANIC`
  - その他: `REVERSAL`

## 6. スコアトレンド（`core/dpa/dpa_scores.py`）

### 6.1 実履歴系列

- `scores_history.json` から銘柄別 `total` を日付昇順抽出
- `latest_dvc` のみ存在し履歴が無ければ 1 点系列として採用

### 6.2 タイムマシン逆算（履歴不足時）

- 目標点数は最大 10 点
- 不足分 `need` がある場合:
  - 過去株価を取得
  - 各過去時点までの部分系列で `momentum_score` を再計算
  - `value` / `safety` は最新値固定
  - `pseudo_total = 0.4*value + 0.4*safety + 0.2*momentum`
- 疑似系列 + 実系列を結合し、末尾 10 点を使用

### 6.3 回帰と正規化

- 点数が 3 未満なら `trend=0.0`
- `slope = polyfit(x=0..n-1, y=score, deg=1)[0]`
- `trend = clip(slope / 5.0, -1.0, 1.0)`
- 返却:
  - `last`: 直近 total
  - `level`: `clip(last/100, 0, 1)`
  - `trend`: 上記正規化値

## 7. ポートフォリオ用スコア（`core/dpa/dpa_portfolio_score.py`）

- 防御強度:
  - `defense = clip((target_cash_ratio - 0.4) / 0.4, 0, 1)`
- 補正係数:
  - `w_beta_penalty = 5 + 15*defense`
  - `w_r2_penalty = 5 + 10*defense`
  - `w_alpha_bonus = 50 + 50*(1-defense)`
  - `w_atr_penalty = 0.3 + 0.4*defense`
- 補正:
  - 高 `beta`, 高 `r2`, 高 `atr` を減点
  - 正 `alpha` を加点
- 最終:
  - `score = clip(base + adj, 0, 150)`

## 8. 目標構成比（`core/dpa/dpa_weights.py`）

- 現金以外の配分枠:
  - `non_cash = 1 - target_cash_ratio`
- 銘柄 i のベース値:
  - `base_raw_i = alpha_level*level_i + beta_trend*trend_i`（既定 `0.7`, `0.3`）
  - `base_raw_i <= 0` は除外
- リスク補正（連続係数）:
  - `beta_penalty`, `r2_penalty`, `atr_penalty`, `alpha_boost` を乗算
  - `risk_factor = clip(product, 0.5, 1.5)`
- 生値:
  - `raw_i = base_raw_i * risk_factor`
- 正規化:
  - `w_i = non_cash * raw_i / sum(raw)`
- `allocation_tickers` 指定時:
  - その集合のみで正規化し、他銘柄は `0`

注記: `ignore_trend` 分岐は存在せず、全銘柄で常に `trend` を使う。

## 9. 売却判定（`core/dpa/dpa_purge.py`）

- 対象は `holdings` のみ
- 金額超過のみで判定:
  - `current_value = shares * price`
  - `target_value = total_capital_actual * target_weight`
  - `excess_value = current_value - target_value`
  - `excess_value <= 0` は売却なし
- ロット算出（非対称丸め）:
  - `lot_cost = price * lot_size`
  - `excess_lots = excess_value / lot_cost`
  - `base_lots = floor(excess_lots)`
  - `remainder = excess_lots - base_lots`
  - `remainder >= purge_lot_threshold` なら `sell_lots = base_lots + 1`
  - 最後に `sell_lots = min(sell_lots, held_lots)`（空売り防止）
- `sell_shares > 0` のみ `PurgeItem` を生成
- 理由:
  - `PANIC`: `MACRO_PANIC`
  - その他: `SCORE_DECAY`

## 10. 購入判定（`core/dpa/dpa_draft.py`）

- `PANIC` または予算 `<=0` は即終了
- 候補抽出:
  - `watching_snapshots` のうち `momentum_score >= threshold`
  - 候補順は `portfolio_score` 降順
- 動的 N 最適化:
  - `N=1..max_draft_candidates` で上位 N 候補を仮想組入
  - `virtual_tickers = holding_tickers ∪ candidate_tickers`
  - 各シナリオで `compute_target_weights()` を再計算
- 各銘柄の購入上限:
  - `target_jpy = total_cap * simulated_weight`
  - `target_jpy = min(target_jpy, min(max_position_pct*total_cap, max_position_jpy))`
  - ロット制約とシナリオ残予算制約で `lots` を決定
- シナリオ評価:
  - `utilization = spent / sim_budget`
  - `weighted_score = sum(score_i*budget_i) / spent`
  - `scenario_score = weighted_score * (1 + 0.1*count) * utilization`
- 最高シナリオを採用して `recommendations` を返す

## 11. ウォッチリスト維持ルール（`core/utils/watchlist_io.py`）

- `watchlist.json` は `WATCHING` と `HOLDING` を同居
- 上限超過時:
  - `HOLDING` は削除しない
  - `WATCHING` の最下位を 1 件削除（`portfolio_scores` 優先、無ければ `total_score`）
- `positions_from_watchlist()` が DPA 向けポジション辞書を復元

## 12. 日次キャッシュ（`core/utils/daily_cache.py`）

- 保存対象:
  - benchmark 履歴
  - peer の `currentPrice/bookValue/trailingEps`
  - VI 履歴（任意）
- fresh 判定は曜日・時刻込み:
  - 週末: 直近金曜更新で fresh
  - 平日カットオフ前: 直近営業日更新で fresh
  - 平日カットオフ後: 当日更新のみ fresh

## 13. レポート組み立て

### 13.1 バッチ出力（`DpaDailyReport`）

- `report_text` は `format_report()` がテキスト整形
- `last_report.json` は毎回更新
- 既存 `last_report` の `data_date` が新規と異なる場合のみ `previous_report.json` に退避

### 13.2 BFF 統合（`web/api.py::_merge_report_data`）

- `last_report` + `previous_report` + 現在 `watchlist`/positions を結合
- 追加計算:
  - `unrealized_pnl`
  - `rank_change`
  - `price_change`
  - 前日比較用 `prev_*` 値

## 14. 主要データファイル

- `config.yaml`: 設定
- `data/watchlist.json`: ウォッチ + 保有
- `portfolio_state.json`: 現金
- `data/daily_cache.json`: マクロ/ピアキャッシュ
- `data/scores_history.json`: 日次 total 履歴
- `output/<ticker>.json`: DVC 個別出力
- `data/last_report.json`: 最新レポート
- `data/previous_report.json`: 前回レポート
- `data/run_status.json`: バッチ進捗状態

## 15. メール送信ロジック（`send_daily_report.py`）

- 実行時にまず `daily_routine.py` をサブプロセス実行
- 成功時:
  - `last_report.json` と `previous_report.json` を使って HTML レポート生成
  - 保有・ウォッチの前日差分色付け（増=赤、減=緑）
- 失敗時:
  - stderr/stdout をまとめた失敗通知 HTML を送信
- Gmail OAuth:
  - `token.json` が期限切れ/失効なら `RefreshError` を捕捉して再認証へフォールバック
- `daily_report.enabled=false` のときは送信をスキップ

# DVC + DPA（Dynamic Value & Catalyst / Dynamic Portfolio Architect）

日本株のスコアリング（Value / Safety / Momentum）と、スコア・マクロに基づくポートフォリオ構築（DPA）を一括で行う日次バッチです。

## 必要な環境

- **Python 3.9 以上**（推奨: 3.10+）
  - キャッシュの「6:00 JST 以降」判定で `zoneinfo` を使用するため、3.9 未満の場合はタイムゾーンが意図とずれる可能性があります。
- 依存: `requirements.txt` を参照
- **LLM 利用時のみ**: `openai` が `requirements.txt` に含まれています。`OPENAI_API_KEY` を環境変数で設定してください。

## セットアップ

```bash
pip install -r requirements.txt
```

設定はプロジェクト直下の **`config.yaml` 1 ファイル**だけです（リポジトリにひな形同梱）。編集して保存してください。  
別ファイルを使う場合は `--config` でパスを指定できます。  
設定値（数値・パス）は `config_loader` で型変換・デフォルト補完されます。

## 日次実行

```bash
python -m daily_routine
```

（`--config path/to.yaml` で明示したいときだけ指定。省略時は `config.yaml` を読みます。）

LLM を使わない（推奨）:

```bash
python -m daily_routine --no-llm
```

設定で `llm.enabled: false` にしていれば `--no-llm` は省略可能です。

## 1 銘柄だけ DVC を実行する（PoC）

```bash
python -m core.dvc.dvc_phase1 --ticker 7203.T --config config.yaml
# LLM を使わず数値のみ
python -m core.dvc.dvc_phase1 --ticker 7203.T --config config.yaml --dry-run
```

## 主なファイル・パス

| 用途 | ファイル／パス | 設定で変更可能 |
|------|-----------------|----------------|
| ウォッチリスト（保有株数・平均単価は HOLDING 行） | `data/watchlist.json` | `--watchlist` |
| 現金残高など | `portfolio_state.json` | `dpa.portfolio_path` |
| セクター・ピア定義 | `data/sector_peers.json` | `dpa.sector_peers_path` |
| 日次キャッシュ（ベンチマーク・VI等） | `data/daily_cache.json` | `cache.cache_path` または `dpa.cache_path` |
| スコア履歴 | `data/scores_history.json` | `dpa.scores_history_path` |
| 最終レポート | `data/last_report.json` | — |
| DVC 出力 | `output/<ticker>.json` | `--output-dir` |

パスを変えたい場合は `config.yaml` の `dpa` / `cache` 配下のコメントを参照してください。  
`--verbose` を付けると使用した config パス・cache_path・sector_peers_path 等が stderr に出力されます。

## スコア履歴の日付について

`scores_history.json` の日付キーは **バッチを実行した日（JST の「今日」）** です。  
株価データの最終取引日ではありません。各銘柄の株価の最終日は `output/<ticker>.json` の `data_overview.price_history.date_max` 等を参照してください。

## 主要モジュール（リファクタリング後の構成）

- **daily_routine.py**（ルート） — 日次バッチの入口（DVC → マクロ → パージ → ドラフト → レポート）
- **core/dvc/** — DVC: `scoring.py`, `schema.py`, `indicators.py`, `data_fetcher.py`, `ai_agent.py`, `dvc_batch.py`, `dvc_phase1.py`
- **core/dpa/** — DPA: `dpa_macro.py`, `dpa_weights.py`, `dpa_portfolio_score.py`, `dpa_purge.py`, `dpa_draft.py`, `dpa_scores.py`, `dpa_schema.py`
- **core/utils/** — 共通: `watchlist_io.py`, `io_utils.py`, `daily_cache.py`, `config_loader.py`
- **data/** — ウォッチリスト・ポジション・キャッシュ・スコア履歴・レポート等の JSON

詳細な処理フローは `docs/DVC_FLOWCHARTS.md` を参照してください。

## テスト

```bash
pip install pytest
pytest tests/ -v
```

## 改善履歴

`docs/IMPROVEMENTS.md` に過去の改善指摘をまとめてあります。多くは本リポジトリで対応済みです。

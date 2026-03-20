from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.utils.config_loader import get_validated_config, load_merged_config
from core.utils.daily_cache import DEFAULT_CACHE_PATH, get_macro_and_peers_data
from core.utils.io_utils import format_data_overview, save_output_json
from core.dvc.scoring import run_dvc_for_ticker


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DVC Phase 1 PoC runner")
    parser.add_argument("--ticker", required=True, help="対象銘柄ティッカー（例: 3197.T）")
    parser.add_argument(
        "--benchmark_ticker", help="ベンチマークティッカー（例: 1306.T）"
    )
    parser.add_argument(
        "--years",
        type=int,
        help="過去データ取得年数（デフォルトはプロジェクトの config.yaml）",
    )
    parser.add_argument(
        "--output",
        help="JSON出力ファイルパス（未指定時は output/<ticker>.json）",
    )
    parser.add_argument(
        "--config",
        help="読み込む設定ファイル（YAML）。未指定時はプロジェクト直下の config.yaml（存在すれば）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="LLMを呼ばずに数値スコアのみ計算して標準出力に表示",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="データ取得の概要を詳細表示（data_overview を標準エラーに出力）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.config:
        cfg_path = Path(args.config)
        if not cfg_path.exists():
            print(f"設定ファイルがありません: {cfg_path}", file=sys.stderr)
            return 1
        raw_cfg = load_merged_config(cfg_path)
    else:
        raw_cfg = load_merged_config(None)
    cfg = get_validated_config(raw_cfg)

    benchmark_ticker = args.benchmark_ticker or cfg.get("benchmark_ticker")
    years = args.years or int(cfg.get("years", 5))
    output_dir = str(cfg.get("output_dir", "output"))
    sector_peers_path = str(Path(cfg.get("sector_peers_path", "data/sector_peers.json")).resolve())
    if not Path(sector_peers_path).exists():
        print(f"sector_peers が見つかりません: {sector_peers_path}", file=sys.stderr)
        return 1

    llm_enabled = not args.dry_run

    # 日次キャッシュ: 最終更新日が今日ならキャッシュから読込、違えば yfinance で取得して保存（VI も vi_ticker 指定時は取得）
    vi_ticker = cfg.get("vi_ticker")
    cache_path = str(Path(cfg.get("cache_path", DEFAULT_CACHE_PATH)).resolve())
    bench_df, peers_data, _ = get_macro_and_peers_data(
        benchmark_ticker=benchmark_ticker,
        years=years,
        sector_peers_path=sector_peers_path,
        cache_path=cache_path,
        vi_ticker=vi_ticker,
    )

    result = run_dvc_for_ticker(
        ticker=args.ticker,
        benchmark_ticker=benchmark_ticker,
        years=years,
        sector_peers_path=sector_peers_path,
        llm_enabled=llm_enabled,
        llm_client=None,
        bench_df=bench_df,
        peers_data=peers_data,
    )

    # データ取得の概要を常に標準エラーに表示（--verbose で詳細）
    if result.data_overview:
        summary = format_data_overview(result.data_overview, verbose=args.verbose)
        print("--- データ取得概要 ---", file=sys.stderr)
        print(summary, file=sys.stderr)
        print("---", file=sys.stderr)

    if args.dry_run:
        print(result.model_dump_json(indent=2))
        return 0

    out_path = args.output or str(Path(output_dir) / f"{args.ticker}.json")
    save_output_json(result, out_path)
    print(f"Saved output to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


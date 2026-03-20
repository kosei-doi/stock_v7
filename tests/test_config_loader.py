"""config_loader のユニットテスト。"""
from __future__ import annotations

from pathlib import Path

from core.utils.config_loader import (
    get_validated_config,
    load_config,
    load_merged_config,
    watchlist_max_items_from_raw_config,
    DEFAULT_BENCHMARK_TICKER,
    DEFAULT_YEARS,
    DEFAULT_SECTOR_PEERS_PATH,
    DEFAULT_CACHE_PATH,
    DEFAULT_WATCHLIST_MAX_ITEMS,
)


def test_load_config_empty_when_no_example_and_no_path(tmp_path):
    # default_to_project_yaml=False かつ config_path が無い → 空
    cfg = load_config(None, default_to_project_yaml=False)
    assert cfg == {}
    cfg = load_config(tmp_path / "nonexistent.yaml", default_to_project_yaml=False)
    assert cfg == {}


def test_load_config_reads_single_file(tmp_path):
    """指定した YAML ファイルの内容をそのまま読む。"""
    user_yaml = tmp_path / "myconfig.yaml"
    user_yaml.write_text("benchmark_ticker: '9999.T'\nyears: 3\n", encoding="utf-8")
    cfg = load_config(user_yaml, default_to_project_yaml=True)
    assert cfg.get("benchmark_ticker") == "9999.T"
    assert cfg.get("years") == 3


def test_load_config_partial_yaml(tmp_path):
    """単一ファイルで dpa の一部だけでも読み込める。欠損は get_validated_config が補完する。"""
    user_yaml = tmp_path / "partial.yaml"
    user_yaml.write_text(
        "dpa:\n  mu_cash: 0.99\n",
        encoding="utf-8",
    )
    cfg = load_config(user_yaml, default_to_project_yaml=True)
    dpa = cfg.get("dpa") or {}
    assert dpa.get("mu_cash") == 0.99
    v = get_validated_config(cfg)
    assert v["mu_cash"] == 0.99
    assert v["benchmark_ticker"] == DEFAULT_BENCHMARK_TICKER


def test_load_merged_config_none_uses_project_yaml_if_exists():
    """load_merged_config(None) が例外なく dict を返す（プロジェクトに config.yaml があればその内容）。"""
    c = load_merged_config(None)
    assert isinstance(c, dict)
    assert "benchmark_ticker" in c or len(c) >= 0


def test_get_validated_config_coerces_types():
    """文字列の数値が int/float に変換される。"""
    raw = {
        "years": "5",
        "dpa": {"total_capital_jpy": "5000000", "mu_cash": "0.4"},
    }
    cfg = get_validated_config(raw)
    assert cfg["years"] == 5
    assert cfg["total_capital_jpy"] == 5000000.0
    assert cfg["mu_cash"] == 0.4


def test_watchlist_max_items_from_raw_config_variants():
    assert watchlist_max_items_from_raw_config({}) == DEFAULT_WATCHLIST_MAX_ITEMS
    assert watchlist_max_items_from_raw_config({"watchlist": {"max_items": 48}}) == 48
    assert watchlist_max_items_from_raw_config({"watchlist_max_items": 52}) == 52
    # ネストが dict でないときはトップレベルのみ
    assert watchlist_max_items_from_raw_config({"watchlist": None, "watchlist_max_items": 40}) == 40


def test_get_validated_config_defaults():
    """キーが無い場合はデフォルト値。"""
    cfg = get_validated_config({})
    assert cfg["benchmark_ticker"] == DEFAULT_BENCHMARK_TICKER
    assert cfg["years"] == DEFAULT_YEARS
    assert cfg["sector_peers_path"] == DEFAULT_SECTOR_PEERS_PATH
    assert cfg["cache_path"] == DEFAULT_CACHE_PATH

"""config_loader のユニットテスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.utils.config_loader import (
    get_validated_config,
    load_config,
    DEFAULT_BENCHMARK_TICKER,
    DEFAULT_YEARS,
    DEFAULT_SECTOR_PEERS_PATH,
    DEFAULT_CACHE_PATH,
)


def test_load_config_empty_when_no_example_and_no_path(tmp_path):
    # use_example_as_base=False かつ config_path が無い → 空
    cfg = load_config(None, use_example_as_base=False)
    assert cfg == {}
    cfg = load_config(tmp_path / "nonexistent.yaml", use_example_as_base=False)
    assert cfg == {}


def test_load_config_merge_order(tmp_path):
    """ユーザー設定が example を上書きする。"""
    user_yaml = tmp_path / "config.yaml"
    user_yaml.write_text("benchmark_ticker: '9999.T'\nyears: 3\n", encoding="utf-8")
    cfg = load_config(user_yaml, use_example_as_base=True)
    # example があれば example のキー + user の上書き
    assert cfg.get("benchmark_ticker") == "9999.T"
    assert cfg.get("years") == 3


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


def test_get_validated_config_defaults():
    """キーが無い場合はデフォルト値。"""
    cfg = get_validated_config({})
    assert cfg["benchmark_ticker"] == DEFAULT_BENCHMARK_TICKER
    assert cfg["years"] == DEFAULT_YEARS
    assert cfg["sector_peers_path"] == DEFAULT_SECTOR_PEERS_PATH
    assert cfg["cache_path"] == DEFAULT_CACHE_PATH

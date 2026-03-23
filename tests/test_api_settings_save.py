"""設定保存: YAML の null ネストでも落ちないことのテスト。"""


def test_flat_to_config_repairs_null_watchlist(monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {
            "watchlist": None,
            "benchmark_ticker": "1306.T",
            "dpa": {"vi_ticker": "^VIX"},
        },
    )
    cfg = api._flat_to_config({"watchlist_max_items": 50})
    assert isinstance(cfg["watchlist"], dict)
    assert cfg["watchlist"]["max_items"] == 50


def test_flat_to_config_repairs_null_dpa(monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {"benchmark_ticker": "1306.T", "dpa": None},
    )
    cfg = api._flat_to_config({"vi_ticker": "^VIX"})
    assert isinstance(cfg["dpa"], dict)
    assert cfg["dpa"]["vi_ticker"] == "^VIX"


def test_flat_to_config_accepts_purge_lot_threshold(monkeypatch):
    import web.api as api

    monkeypatch.setattr(
        api,
        "_load_config_raw",
        lambda: {"benchmark_ticker": "1306.T", "dpa": {}},
    )
    cfg = api._flat_to_config({"purge_lot_threshold": 0.65})
    assert cfg["dpa"]["purge_lot_threshold"] == 0.65

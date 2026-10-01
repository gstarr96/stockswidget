from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone

import pytest

from conftest import REPO_ROOT
from stocknews import cli, tracker
from stocknews.config import (
    DEFAULT_TRACKER_TICKERS,
    MAX_TRACKER_TICKERS,
    Settings,
    load_settings,
    save_tracker_tickers,
)
from stocknews.errors import ConfigError, MarketDataError
from stocknews.market import PriceSeries

NOW = datetime(2026, 9, 24, 15, 0, tzinfo=timezone.utc)


class FakeMarket:
    def __init__(self, unknown=(), down=()):
        self.unknown = set(unknown)
        self.down = set(down)

    def intraday(self, symbol):
        if symbol in self.unknown:
            raise MarketDataError(f"No price data for {symbol}", not_found=True)
        if symbol in self.down:
            raise MarketDataError("Yahoo is down", status=503)
        return PriceSeries(
            symbol=symbol,
            name=f"{symbol} Inc.",
            price=110.0,
            previous_close=100.0,
            closes=(100.0, 105.0, 110.0),
        )


def write_config(paths, text: str, newline: str = "\n") -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_bytes(text.replace("\n", newline).encode("utf-8"))


def test_defaults_are_the_five_starter_stocks(paths):
    settings = load_settings(paths, environ={})

    assert (
        settings.tracker_tickers
        == DEFAULT_TRACKER_TICKERS
        == (
            "AAPL",
            "NFLX",
            "PLTR",
            "SPCX",
            "NVDA",
        )
    )


def test_blank_tracker_list_means_no_stocks(paths):
    write_config(paths, "[tracker]\ntickers =\n")

    assert load_settings(paths, environ={}).tracker_tickers == ()


def test_too_many_tickers_is_a_config_error(paths):
    tickers = ", ".join(f"T{i}" for i in range(MAX_TRACKER_TICKERS + 1))
    write_config(paths, f"[tracker]\ntickers = {tickers}\n")

    with pytest.raises(ConfigError):
        load_settings(paths, environ={})


def test_saving_rewrites_only_the_tickers_line(paths):
    original = (
        "[ai]\nopenai_api_key = sk-secret\n\n"
        "[tracker]\n; my favourites\ntickers = AAPL\n\n"
        "[charts]\ninterval = 5m\n"
    )
    write_config(paths, original, newline="\r\n")

    save_tracker_tickers(paths, ["AAPL", "AMD"])

    raw = paths.config_file.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n") > 0
    assert raw.decode().replace("\r\n", "\n") == original.replace(
        "tickers = AAPL", "tickers = AAPL, AMD"
    )
    assert load_settings(paths, environ={}).tracker_tickers == ("AAPL", "AMD")


def test_saving_appends_a_tracker_section_when_missing(paths):
    write_config(paths, "[ai]\nprovider = openai\n")

    save_tracker_tickers(paths, ["TSLA"])

    settings = load_settings(paths, environ={})
    assert settings.tracker_tickers == ("TSLA",)
    assert settings.ai_provider == "openai"


def test_add_validates_and_saves(paths):
    settings = Settings(tracker_tickers=("AAPL",))

    updated, problems = tracker.add_tickers(
        paths, settings, FakeMarket(unknown={"ZZZZ"}), "amd, aapl, brk.b, ZZZZ, not valid"
    )

    assert updated.tracker_tickers == ("AAPL", "AMD", "BRK-B")
    assert problems == [
        "Yahoo Finance has no stock called ZZZZ.",
        "'not valid' is not a valid ticker.",
    ]
    assert load_settings(paths, environ={}).tracker_tickers == ("AAPL", "AMD", "BRK-B")


def test_add_stops_at_the_tile_limit(paths):
    full = tuple(f"T{i}" for i in range(MAX_TRACKER_TICKERS))

    updated, problems = tracker.add_tickers(
        paths, Settings(tracker_tickers=full), FakeMarket(), "AMD"
    )

    assert updated.tracker_tickers == full
    assert problems == [f"The watchlist holds up to {MAX_TRACKER_TICKERS} stocks."]


def test_add_raises_when_yahoo_is_down(paths):
    with pytest.raises(MarketDataError):
        tracker.add_tickers(paths, Settings(), FakeMarket(down={"AMD"}), "AMD")


def test_remove_saves_the_shorter_list(paths):
    updated = tracker.remove_tickers(paths, Settings(), "nflx,SPCX")

    assert updated.tracker_tickers == ("AAPL", "PLTR", "NVDA")
    assert load_settings(paths, environ={}).tracker_tickers == ("AAPL", "PLTR", "NVDA")


def test_payload_has_one_tile_per_ticker_in_order():
    settings = Settings(tracker_tickers=("NVDA", "AAPL", "DOWN"))

    payload = tracker.build_tracker_payload(settings, FakeMarket(down={"DOWN"}), now=NOW)

    assert [tile["symbol"] for tile in payload["tiles"]] == ["NVDA", "AAPL", "DOWN"]
    nvda = payload["tiles"][0]
    assert nvda["priceText"] == "110.00"
    assert nvda["changePctText"] == "+10.00%"
    assert nvda["changePointsText"] == "+10.00"
    assert nvda["direction"] == "up"
    assert len(nvda["points"]) == 3
    assert payload["tiles"][2]["available"] is False
    assert payload["status"] == "warning"
    assert "DOWN" in payload["message"]
    assert payload["statusText"].startswith("Updated")


def test_empty_watchlist_prompts_to_add():
    payload = tracker.build_tracker_payload(Settings(tracker_tickers=()), FakeMarket(), now=NOW)

    assert payload["tiles"] == []
    assert payload["status"] == "ok"
    assert payload["statusText"] == "Click + to add a stock"


def test_cli_tracker_mode_writes_watchlist_json(paths, monkeypatch):
    monkeypatch.setattr(cli, "YahooFinanceClient", lambda interval: FakeMarket())
    args = ["--resources", str(paths.resources), "--config-dir", str(paths.config_dir)]

    assert cli.main([*args, "--tracker", "--add", "AMD", "--remove", "NFLX"]) == 0

    data = json.loads(paths.tracker_file.read_text(encoding="ascii"))
    assert [t["symbol"] for t in data["tiles"]] == ["AAPL", "PLTR", "SPCX", "NVDA", "AMD"]
    assert not paths.output_file.exists()


def test_cli_tracker_failure_keeps_previous_tiles(paths, monkeypatch):
    paths.data_dir.mkdir(parents=True)
    paths.tracker_file.write_text(json.dumps({"tiles": [{"symbol": "AAPL"}]}), encoding="ascii")
    write_config(paths, "[charts]\ninterval = 1h\n")
    args = ["--resources", str(paths.resources), "--config-dir", str(paths.config_dir)]

    assert cli.main([*args, "--tracker"]) == 1

    data = json.loads(paths.tracker_file.read_text(encoding="ascii"))
    assert data["status"] == "error"
    assert data["tiles"] == [{"symbol": "AAPL"}]


def test_add_requires_tracker_mode():
    with pytest.raises(SystemExit):
        cli.main(["--add", "AMD"])


def test_generated_watchlist_skin_is_up_to_date():
    script = REPO_ROOT / "tools" / "generate_watchlist_skin.py"
    spec = importlib.util.spec_from_file_location("generate_watchlist_skin", script)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    assert generator.MAX_TILES == MAX_TRACKER_TICKERS
    assert generator.OUTPUT.read_bytes() == generator.render().encode("ascii"), (
        "Watchlist.ini is stale: run python tools/generate_watchlist_skin.py"
    )

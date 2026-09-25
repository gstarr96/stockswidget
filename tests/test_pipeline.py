from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

from stocknews import cli, pipeline
from stocknews.ai import AIProvider, AIReply, Citation
from stocknews.config import Settings
from stocknews.errors import AIError, ConfigError, MarketDataError
from stocknews.market import PriceSeries

SESSION_START = datetime(2026, 9, 24, 13, 30, tzinfo=timezone.utc)
SESSION_END = SESSION_START + timedelta(hours=6, minutes=30)
DURING = SESSION_START + timedelta(hours=1)
AFTER = SESSION_END + timedelta(hours=1)
SETTINGS = Settings(openai_api_key="sk", story_count=3, summary_refresh_minutes=60)


class FakeMarket:
    def __init__(self, movers=("UP1", "DN1", "UP2"), down=(), session_date="2026-09-24"):
        self.mover_list = list(movers)
        self.down = set(down)
        self.session_date = session_date
        self.requested = []

    def movers(self, count):
        return self.mover_list[:count]

    def intraday(self, symbol):
        self.requested.append(symbol)
        if symbol in self.down:
            raise MarketDataError(f"Price data for {symbol} is unavailable", status=503)
        return PriceSeries(
            symbol=symbol,
            name=f"{symbol} Inc.",
            price=101.0,
            previous_close=100.0,
            closes=(100.0, 100.5, 101.0),
            session_date=self.session_date,
            trading_start=int(SESSION_START.timestamp()),
            trading_end=int(SESSION_END.timestamp()),
        )


class FakeAI(AIProvider):
    name = "Fake"

    def __init__(self, fail=None):
        self.fail = fail or {}
        self.researched = []

    def research(self, system, prompt):
        symbol = prompt.split("(", 1)[1].split(")", 1)[0]
        self.researched.append(symbol)
        if symbol in self.fail:
            raise self.fail[symbol]
        body = {
            "headline": f"{symbol} moves on news",
            "summary": f"Why {symbol} moved.",
            "sentiment": "positive",
            "source_name": "Reuters",
            "source_url": f"https://reuters.com/{symbol}",
        }
        return AIReply(json.dumps(body), (Citation("R", f"https://reuters.com/{symbol}"),))


def run(paths, ai=None, market=None, settings=SETTINGS, now=DURING, **kwargs):
    services = pipeline.Services(market=market or FakeMarket(), ai=ai or FakeAI())
    return pipeline.run(settings, paths, services, now=now, **kwargs)


def tickers(payload):
    return [story["ticker"] for story in payload["stories"]]


def test_run_researches_movers_in_order(paths):
    ai = FakeAI()

    payload = run(paths, ai=ai)

    assert payload["status"] == "ok"
    assert tickers(payload) == ["UP1", "DN1", "UP2"]
    assert sorted(ai.researched) == ["DN1", "UP1", "UP2"]
    assert payload["stories"][0]["url"] == "https://reuters.com/UP1"
    assert payload["stories"][0]["chart"]["direction"] == "up"
    assert [i["name"] for i in payload["indices"]] == ["S&P 500", "Dow Jones", "Nasdaq"]


def test_watchlist_replaces_movers(paths):
    settings = Settings(openai_api_key="sk", watchlist=("AAPL", "MSFT"))

    payload = run(paths, settings=settings)

    assert tickers(payload) == ["AAPL", "MSFT"]


def test_cache_is_time_limited_while_market_is_open(paths):
    ai = FakeAI()

    run(paths, ai=ai, now=DURING)
    run(paths, ai=ai, now=DURING + timedelta(minutes=30))
    assert len(ai.researched) == 3

    run(paths, ai=ai, now=DURING + timedelta(minutes=61))
    assert len(ai.researched) == 6


def test_cache_lasts_all_night_after_the_close(paths):
    ai = FakeAI()

    run(paths, ai=ai, now=AFTER)
    run(paths, ai=ai, now=AFTER + timedelta(hours=10))

    assert len(ai.researched) == 3


def test_new_session_and_new_movers_are_researched(paths):
    ai = FakeAI()
    run(paths, ai=ai, now=AFTER)

    run(paths, ai=ai, market=FakeMarket(movers=("UP1", "NEW")), now=AFTER)
    assert ai.researched[3:] == ["NEW"]

    run(paths, ai=ai, market=FakeMarket(session_date="2026-09-25"), now=AFTER)
    assert len(ai.researched) == 7


def test_force_and_model_change_bypass_cache(paths):
    ai = FakeAI()
    run(paths, ai=ai, now=AFTER)

    run(paths, ai=ai, now=AFTER, force_summaries=True)
    assert len(ai.researched) == 6

    run(paths, ai=ai, now=AFTER, settings=Settings(openai_api_key="sk", openai_model="other"))
    assert len(ai.researched) == 9


def test_partial_failure_is_a_warning_with_older_summary_kept(paths):
    run(paths, now=DURING)

    ai = FakeAI(fail={"DN1": AIError("timeout")})
    payload = run(paths, ai=ai, now=DURING + timedelta(hours=2))

    assert payload["status"] == "warning"
    assert "DN1" in payload["message"] and "timeout" in payload["message"]
    assert tickers(payload) == ["UP1", "DN1", "UP2"]


def test_failure_without_any_story_raises(paths):
    ai = FakeAI(fail={s: AIError("down") for s in ("UP1", "DN1", "UP2")})

    with pytest.raises(AIError):
        run(paths, ai=ai)


def test_rejected_key_aborts_refresh(paths):
    with pytest.raises(ConfigError):
        run(paths, ai=FakeAI(fail={"UP1": ConfigError("bad key")}))


def test_stock_without_price_data_is_skipped(paths):
    market = FakeMarket(down={"DN1"})
    ai = FakeAI()

    payload = run(paths, ai=ai, market=market)

    assert tickers(payload) == ["UP1", "UP2"]
    assert "DN1" not in ai.researched


def test_missing_key_still_shows_indices(paths):
    payload = pipeline.run(Settings(), paths, pipeline.Services(market=FakeMarket()), now=DURING)

    assert payload["status"] == "setup"
    assert "OpenAI API key" in payload["message"]
    assert payload["indices"][0]["available"] is True
    assert payload["stories"] == []


@pytest.fixture
def restore_logging():
    root = logging.getLogger()
    original = root.handlers[:]
    yield
    for handler in root.handlers[:]:
        if handler not in original:
            handler.close()
            root.removeHandler(handler)
    root.handlers[:] = original


@pytest.mark.usefixtures("restore_logging")
def test_cli_failure_keeps_previous_stories(paths, monkeypatch):
    previous = {"stories": [{"ticker": "NVDA"}], "indices": [{"name": "S&P 500"}]}
    paths.data_dir.mkdir(parents=True)
    paths.output_file.write_text(json.dumps(previous), encoding="utf-8")

    def boom(*args, **kwargs):
        raise AIError("provider down")

    monkeypatch.setattr(pipeline, "run", boom)
    code = cli.main(["--resources", str(paths.resources), "--config-dir", str(paths.config_dir)])

    written = json.loads(paths.output_file.read_text(encoding="ascii"))
    assert code == 1
    assert written["status"] == "error"
    assert written["message"] == "provider down"
    assert written["stories"] == previous["stories"]

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import load_fixture
from stocknews.charts import downsample, normalize
from stocknews.errors import DataSourceError, MarketDataError
from stocknews.market import YahooFinanceClient, normalize_ticker, parse_chart, parse_screener


def test_parse_chart_reads_prices_and_session():
    series = parse_chart(load_fixture("yahoo_chart.json"), "AAPL")

    assert series.name == "Apple Inc."
    assert series.closes == (228.5, 229.0, 230.0, 230.5)
    assert series.change == pytest.approx(2.5)
    assert series.change_pct == pytest.approx(2.5 / 228.0 * 100)
    assert series.session_date == "2026-09-24"


def test_market_open_follows_the_regular_trading_period():
    series = parse_chart(load_fixture("yahoo_chart.json"), "AAPL")

    assert series.is_market_open(datetime.fromtimestamp(1790260000, tz=timezone.utc))
    assert not series.is_market_open(datetime.fromtimestamp(1790290000, tz=timezone.utc))


def test_parse_chart_last_session_uses_prior_close_as_baseline():
    day = 86_400
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "SPY", "regularMarketPrice": 12.0, "gmtoffset": 0},
                    "timestamp": [day + 100, day + 200, 2 * day + 100, 2 * day + 200],
                    "indicators": {"quote": [{"close": [9.0, 10.0, 11.0, 12.0]}]},
                }
            ]
        }
    }

    series = parse_chart(payload, "SPY", last_session_only=True)

    assert series.closes == (11.0, 12.0)
    assert series.previous_close == 10.0
    assert series.session_date == "1970-01-03"


def test_parse_chart_not_found_error():
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "x"}}}

    with pytest.raises(MarketDataError) as info:
        parse_chart(payload, "ZZZZ")
    assert info.value.not_found


def test_client_falls_back_to_five_days_before_the_open():
    ranges = []
    empty = {"chart": {"result": [{"meta": {"regularMarketPrice": 5.0}, "timestamp": []}]}}

    def fake_fetch(url, *, params, headers):
        ranges.append(params["range"])
        return empty if params["range"] == "1d" else load_fixture("yahoo_chart.json")

    series = YahooFinanceClient(fetch=fake_fetch).intraday("AAPL")

    assert ranges == ["1d", "5d"]
    assert len(series.closes) == 4


def test_client_marks_http_404_as_not_found():
    def fake_fetch(url, **kwargs):
        raise DataSourceError("HTTP 404", status=404)

    with pytest.raises(MarketDataError) as info:
        YahooFinanceClient(fetch=fake_fetch).intraday("NOPE")
    assert info.value.not_found


def test_parse_screener_keeps_unique_equities_in_order():
    assert parse_screener(load_fixture("yahoo_screener.json")) == ["TWST", "GRAL", "BRK-B"]


def test_parse_screener_rejects_unexpected_payload():
    with pytest.raises(MarketDataError):
        parse_screener({"finance": {"result": []}})


def test_movers_alternate_gainers_and_losers():
    lists = {"day_gainers": ["UP1", "UP2", "UP3"], "day_losers": ["DN1", "UP2", "DN2"]}

    def fake_fetch(url, *, params, headers):
        quotes = [{"symbol": s, "quoteType": "EQUITY"} for s in lists[params["scrIds"]]]
        return {"finance": {"result": [{"quotes": quotes}]}}

    assert YahooFinanceClient(fetch=fake_fetch).movers(4) == ["UP1", "DN1", "UP2", "UP3"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("aapl", "AAPL"), ("BRK.B", "BRK-B"), ("$TSLA", "TSLA"), ("S&P", ""), ("", ""), (None, "")],
)
def test_normalize_ticker(raw, expected):
    assert normalize_ticker(raw) == expected


def test_downsample_keeps_endpoints():
    result = downsample(list(range(100)), 10)

    assert len(result) == 10
    assert result[0] == 0 and result[-1] == 99


def test_normalize_scales_and_places_baseline():
    points, baseline = normalize([10, 20, 15], max_points=10, baseline=12)

    assert points == [0.0, 1.0, 0.5]
    assert baseline == 0.2


def test_normalize_hides_out_of_range_baseline_and_handles_flat_series():
    assert normalize([10, 20], max_points=10, baseline=5)[1] is None
    assert normalize([7, 7, 7], max_points=10) == ([0.5, 0.5, 0.5], None)
    assert normalize([], max_points=10) == ([], None)

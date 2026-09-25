"""Prices, intraday charts and daily movers from Yahoo Finance (no API key needed).

These endpoints are unofficial; everything Yahoo-specific is kept in this module
so it can be swapped for another provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import chain, zip_longest
from typing import Any
from urllib.parse import quote

from .errors import DataSourceError, MarketDataError
from .http import Fetch, request_json

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_SCREENER_URL = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
SECONDS_PER_DAY = 86_400
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:-[A-Z]{1,2})?$")


def normalize_ticker(value: Any) -> str:
    """Upper-case ticker in Yahoo's format (BRK.B -> BRK-B), or '' if it looks invalid."""
    ticker = str(value or "").strip().upper().lstrip("$").replace(".", "-")
    return ticker if TICKER_PATTERN.match(ticker) else ""


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    name: str
    price: float
    previous_close: float | None
    closes: tuple[float, ...]
    session_date: str = ""
    trading_start: int | None = None
    trading_end: int | None = None

    @property
    def change(self) -> float | None:
        if not self.previous_close:
            return None
        return self.price - self.previous_close

    @property
    def change_pct(self) -> float | None:
        change = self.change
        if change is None or not self.previous_close:
            return None
        return change / self.previous_close * 100

    def is_market_open(self, now: datetime) -> bool:
        if self.trading_start is None or self.trading_end is None:
            return False
        return self.trading_start <= now.timestamp() < self.trading_end


class YahooFinanceClient:
    def __init__(self, interval: str = "5m", fetch: Fetch = request_json) -> None:
        self._interval = interval
        self._fetch = fetch

    def intraday(self, symbol: str) -> PriceSeries:
        """Today's session, or the most recent one before the market opens."""
        series = self._fetch_series(symbol, "1d", last_session_only=False)
        if len(series.closes) >= 2:
            return series
        return self._fetch_series(symbol, "5d", last_session_only=True)

    def movers(self, count: int) -> list[str]:
        """The day's biggest US gainers and losers, alternating, biggest moves first."""
        gainers = self._screen("day_gainers", count)
        losers = self._screen("day_losers", count)
        symbols: list[str] = []
        for symbol in chain.from_iterable(zip_longest(gainers, losers)):
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols[:count]

    def _screen(self, screener_id: str, count: int) -> list[str]:
        try:
            payload = self._fetch(
                YAHOO_SCREENER_URL,
                params={"scrIds": screener_id, "count": str(count * 2)},
                headers={"User-Agent": BROWSER_USER_AGENT},
            )
        except DataSourceError as exc:
            raise MarketDataError(
                f"Could not load Yahoo's {screener_id} list: {exc}", status=exc.status
            ) from exc
        return parse_screener(payload)

    def _fetch_series(self, symbol: str, range_: str, *, last_session_only: bool) -> PriceSeries:
        url = YAHOO_CHART_URL.format(symbol=quote(symbol, safe=""))
        try:
            payload = self._fetch(
                url,
                params={"range": range_, "interval": self._interval, "includePrePost": "false"},
                headers={"User-Agent": BROWSER_USER_AGENT},
            )
        except DataSourceError as exc:
            raise MarketDataError(
                f"Price data for {symbol} is unavailable: {exc}",
                status=exc.status,
                not_found=exc.status == 404,
            ) from exc
        return parse_chart(payload, symbol, last_session_only=last_session_only)


def parse_screener(payload: Any) -> list[str]:
    finance = payload.get("finance") if isinstance(payload, dict) else None
    results = finance.get("result") if isinstance(finance, dict) else None
    quotes = results[0].get("quotes") if results and isinstance(results[0], dict) else None
    if not isinstance(quotes, list):
        raise MarketDataError("Yahoo returned an unexpected movers list")

    symbols = []
    for entry in quotes:
        if not isinstance(entry, dict) or entry.get("quoteType") != "EQUITY":
            continue
        symbol = normalize_ticker(entry.get("symbol"))
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def parse_chart(payload: Any, symbol: str, *, last_session_only: bool = False) -> PriceSeries:
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        raise MarketDataError(f"Unexpected chart response for {symbol}")

    error = chart.get("error")
    if error:
        code = str(error.get("code", "")) if isinstance(error, dict) else ""
        raise MarketDataError(f"No price data for {symbol}", not_found=code == "Not Found")

    results = chart.get("result") or []
    if not results or not isinstance(results[0], dict):
        raise MarketDataError(f"No price data for {symbol}", not_found=True)

    result = results[0]
    meta = result.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    timestamps = result.get("timestamp") or []
    quotes = (result.get("indicators") or {}).get("quote") or [{}]
    closes = quotes[0].get("close") or []
    points = [
        (int(t), float(c))
        for t, c in zip(timestamps, closes)
        if isinstance(t, (int, float)) and isinstance(c, (int, float))
    ]

    previous_close = _number(meta.get("chartPreviousClose")) or _number(meta.get("previousClose"))
    if last_session_only and points:
        last_day = (points[-1][0] + offset) // SECONDS_PER_DAY
        earlier = [p for p in points if (p[0] + offset) // SECONDS_PER_DAY < last_day]
        points = [p for p in points if (p[0] + offset) // SECONDS_PER_DAY == last_day]
        if earlier:
            previous_close = earlier[-1][1]

    price = _number(meta.get("regularMarketPrice"))
    if price is None:
        if not points:
            raise MarketDataError(f"No price data for {symbol}")
        price = points[-1][1]

    market_time = meta.get("regularMarketTime")
    if not isinstance(market_time, (int, float)) and points:
        market_time = points[-1][0]
    session_date = ""
    if isinstance(market_time, (int, float)):
        session_date = (
            datetime.fromtimestamp(market_time + offset, tz=timezone.utc).date().isoformat()
        )

    period = ((meta.get("currentTradingPeriod") or {}).get("regular")) or {}
    return PriceSeries(
        symbol=str(meta.get("symbol") or symbol),
        name=str(meta.get("longName") or meta.get("shortName") or symbol),
        price=price,
        previous_close=previous_close,
        closes=tuple(c for _, c in points),
        session_date=session_date,
        trading_start=_integer(period.get("start")),
        trading_end=_integer(period.get("end")),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)

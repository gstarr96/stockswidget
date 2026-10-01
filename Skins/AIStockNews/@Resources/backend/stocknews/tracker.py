"""The Watchlist skin: live prices and charts for the user's own tickers.

Runs every minute or so, so it only talks to Yahoo Finance and never to an AI
provider. The tickers live in the [tracker] section of config.ini.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Protocol

from .config import MAX_TRACKER_TICKERS, Paths, Settings, save_tracker_tickers
from .errors import MarketDataError, StockNewsError
from .market import PriceSeries, normalize_ticker
from .output import SCHEMA_VERSION, clean_text, format_clock, read_json, series_to_dict

log = logging.getLogger(__name__)

TILE_CHART_POINTS = 48
MAX_PARALLEL_FETCHES = 6


class PriceSource(Protocol):
    def intraday(self, symbol: str) -> PriceSeries: ...


def add_tickers(
    paths: Paths, settings: Settings, market: PriceSource, raw: str
) -> tuple[Settings, list[str]]:
    """Add each valid ticker in a comma-separated string. Returns problems to show the user."""
    tickers = list(settings.tracker_tickers)
    problems: list[str] = []
    for entry in _split(raw):
        symbol = normalize_ticker(entry)
        if not symbol:
            problems.append(f"'{entry}' is not a valid ticker.")
            continue
        if symbol in tickers:
            continue
        if len(tickers) >= MAX_TRACKER_TICKERS:
            problems.append(f"The watchlist holds up to {MAX_TRACKER_TICKERS} stocks.")
            break
        try:
            market.intraday(symbol)
        except MarketDataError as exc:
            if not exc.not_found:
                raise
            problems.append(f"Yahoo Finance has no stock called {symbol}.")
            continue
        tickers.append(symbol)

    if tuple(tickers) != settings.tracker_tickers:
        save_tracker_tickers(paths, tickers)
    return replace(settings, tracker_tickers=tuple(tickers)), problems


def remove_tickers(paths: Paths, settings: Settings, raw: str) -> Settings:
    remove = {normalize_ticker(entry) for entry in _split(raw)}
    tickers = tuple(t for t in settings.tracker_tickers if t not in remove)
    if tickers != settings.tracker_tickers:
        save_tracker_tickers(paths, tickers)
    return replace(settings, tracker_tickers=tickers)


def build_tracker_payload(
    settings: Settings,
    market: PriceSource,
    *,
    notes: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    symbols = settings.tracker_tickers
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FETCHES) as pool:
        series = list(pool.map(lambda symbol: _try_series(market, symbol), symbols))

    tiles = [
        series_to_dict(s, symbol=symbol, name=s.name if s else symbol, max_points=TILE_CHART_POINTS)
        for symbol, s in zip(symbols, series)
    ]
    missing = [symbol for symbol, s in zip(symbols, series) if s is None]

    messages = list(notes or [])
    if missing:
        messages.append(f"No price data for {', '.join(missing)} right now.")
    if not symbols:
        status_text = "Click + to add a stock"
    elif missing and len(missing) == len(symbols):
        status_text = "Prices unavailable"
    else:
        status_text = f"Updated {format_clock(now)}"
    return tracker_payload(
        status="warning" if messages else "ok",
        status_text=status_text,
        message=" ".join(messages),
        tiles=tiles,
        generated_at=now,
    )


def failure_payload(paths: Paths, message: str) -> dict[str, Any]:
    """An error payload that keeps the last good tiles on screen."""
    previous = read_json(paths.tracker_file)
    tiles = previous.get("tiles") if isinstance(previous, dict) else None
    return tracker_payload(
        status="error",
        status_text="Update failed",
        message=message,
        tiles=tiles if isinstance(tiles, list) else [],
        generated_at=datetime.now(timezone.utc),
    )


def tracker_payload(
    *,
    status: str,
    status_text: str,
    message: str,
    tiles: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "statusText": clean_text(status_text, 40),
        "message": clean_text(message, 300),
        "generatedAt": generated_at.isoformat(timespec="seconds"),
        "tiles": tiles,
    }


def _split(raw: str) -> list[str]:
    return [entry.strip() for entry in raw.replace(";", ",").split(",") if entry.strip()]


def _try_series(market: PriceSource, symbol: str) -> PriceSeries | None:
    try:
        return market.intraday(symbol)
    except StockNewsError as exc:
        log.warning("%s", exc)
        return None

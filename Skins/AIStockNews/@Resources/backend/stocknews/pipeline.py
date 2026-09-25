"""One widget refresh: pick stocks, fetch charts, research each move with AI, build the payload."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .ai import AIProvider, create_provider
from .config import Paths, Settings
from .errors import ConfigError, StockNewsError
from .market import PriceSeries, YahooFinanceClient
from .output import (
    build_payload,
    format_clock,
    read_json,
    series_to_dict,
    story_to_dict,
    write_json_atomic,
)
from .research import Story, research_story

log = logging.getLogger(__name__)

INDICES = (("^GSPC", "S&P 500"), ("^DJI", "Dow Jones"), ("^IXIC", "Nasdaq"))
STORY_CHART_POINTS = 90
INDEX_CHART_POINTS = 60
MAX_PARALLEL_RESEARCH = 3
CACHE_RETENTION = timedelta(days=4)


class MarketData(Protocol):
    def intraday(self, symbol: str) -> PriceSeries: ...

    def movers(self, count: int) -> list[str]: ...


@dataclass
class Services:
    market: MarketData
    ai: AIProvider | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> Services:
        return cls(
            market=YahooFinanceClient(interval=settings.chart_interval),
            ai=create_provider(settings) if settings.ai_api_key else None,
        )


@dataclass(frozen=True)
class CachedStory:
    story: Story
    researched_at: datetime
    session_date: str
    provider: str
    model: str

    def is_fresh(self, settings: Settings, series: PriceSeries, now: datetime) -> bool:
        """Valid for the whole session once the market closes; time-limited while it's open."""
        if (self.provider, self.model) != (settings.ai_provider, settings.ai_model):
            return False
        if self.session_date != series.session_date:
            return False
        if not series.is_market_open(now):
            return True
        return now - self.researched_at < timedelta(minutes=settings.summary_refresh_minutes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "story": self.story.to_dict(),
            "researchedAt": self.researched_at.isoformat(),
            "sessionDate": self.session_date,
            "provider": self.provider,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: Any) -> CachedStory | None:
        try:
            researched_at = datetime.fromisoformat(data["researchedAt"])
            if researched_at.tzinfo is None:
                researched_at = researched_at.replace(tzinfo=timezone.utc)
            return cls(
                story=Story.from_dict(data["story"]),
                researched_at=researched_at,
                session_date=str(data["sessionDate"]),
                provider=str(data["provider"]),
                model=str(data["model"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def load_cache(path: Path) -> dict[str, CachedStory]:
    data = read_json(path)
    entries = data.get("stories") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return {}
    cache = {}
    for symbol, entry in entries.items():
        cached = CachedStory.from_dict(entry)
        if cached:
            cache[symbol] = cached
    return cache


def save_cache(path: Path, cache: dict[str, CachedStory], now: datetime) -> None:
    kept = {s: c for s, c in cache.items() if now - c.researched_at < CACHE_RETENTION}
    write_json_atomic(
        path, {"version": 2, "stories": {s: c.to_dict() for s, c in sorted(kept.items())}}
    )


def run(
    settings: Settings,
    paths: Paths,
    services: Services,
    *,
    now: datetime | None = None,
    force_summaries: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    indices = [
        series_to_dict(
            _try_series(services.market, symbol),
            symbol=symbol,
            name=name,
            max_points=INDEX_CHART_POINTS,
        )
        for symbol, name in INDICES
    ]

    if settings.missing_keys() or services.ai is None:
        return build_payload(
            status="setup",
            status_text="Setup required",
            message=f"Add your {settings.provider_label} API key to config.ini: "
            "right-click the widget > Edit settings.",
            stories=[],
            indices=indices,
            generated_at=now,
        )

    if settings.watchlist:
        symbols = list(settings.watchlist[: settings.story_count])
    else:
        symbols = services.market.movers(settings.story_count)
    all_series = [s for s in (_try_series(services.market, sym) for sym in symbols) if s]

    cache = load_cache(paths.summary_cache)
    to_research = [
        s
        for s in all_series
        if force_summaries
        or s.symbol not in cache
        or not cache[s.symbol].is_fresh(settings, s, now)
    ]
    researched, failures = _research_all(services.ai, to_research)
    for series in to_research:
        if series.symbol in researched:
            cache[series.symbol] = CachedStory(
                story=researched[series.symbol],
                researched_at=now,
                session_date=series.session_date,
                provider=settings.ai_provider,
                model=settings.ai_model,
            )
    if researched:
        save_cache(paths.summary_cache, cache, now)

    stories = [
        story_to_dict(cache[s.symbol].story, s, max_points=STORY_CHART_POINTS)
        for s in all_series
        if s.symbol in cache
    ]
    if failures and not stories:
        raise next(iter(failures.values()))

    updated = f"Updated {format_clock(now)}"
    if failures:
        failed = ", ".join(sorted(failures))
        first_error = next(iter(failures.values()))
        status, status_text = "warning", f"{updated} (some research failed)"
        message = f"Could not research {failed}: {first_error}"
    elif not stories:
        status, status_text = "warning", updated
        message = "No stock data is available right now."
    else:
        status, status_text, message = "ok", updated, ""

    return build_payload(
        status=status,
        status_text=status_text,
        message=message,
        stories=stories,
        indices=indices,
        generated_at=now,
    )


def _research_all(
    ai: AIProvider, series_list: list[PriceSeries]
) -> tuple[dict[str, Story], dict[str, StockNewsError]]:
    """Research stocks in parallel. A rejected key or bad model aborts the whole refresh."""
    stories: dict[str, Story] = {}
    failures: dict[str, StockNewsError] = {}
    if not series_list:
        return stories, failures

    log.info("Researching %s with %s", ", ".join(s.symbol for s in series_list), ai.name)
    workers = min(MAX_PARALLEL_RESEARCH, len(series_list))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(research_story, ai, s): s.symbol for s in series_list}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                stories[symbol] = future.result()
            except StockNewsError as exc:
                log.warning("Research failed for %s: %s", symbol, exc)
                failures[symbol] = exc

    config_errors = [e for e in failures.values() if isinstance(e, ConfigError)]
    if config_errors:
        raise config_errors[0]
    return stories, failures


def _try_series(market: MarketData, symbol: str) -> PriceSeries | None:
    try:
        return market.intraday(symbol)
    except StockNewsError as exc:
        log.warning("%s", exc)
        return None

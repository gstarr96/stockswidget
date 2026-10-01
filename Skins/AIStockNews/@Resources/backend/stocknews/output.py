"""Builds and writes data/widget.json, the only file the Rainmeter skin reads.

The schema is documented in docs/data-format.md. Bump SCHEMA_VERSION on any
breaking change and update Scripts/Widget.lua to match.
"""

from __future__ import annotations

import json
import os
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from .charts import normalize
from .market import PriceSeries
from .research import Story

SCHEMA_VERSION = 1

# Rainmeter's Lua bridge does not reliably round-trip non-ASCII text, so
# everything the skin displays is reduced to ASCII.
_ASCII_REPLACEMENTS = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": " - ",
    "\u2026": "...",
    "\u00a0": " ",
    "\u2022": "-",
    "\u20ac": "EUR ",
    "\u00a3": "GBP ",
}
_URL_FORBIDDEN = set(" \"'[]<>\t\r\n")


def clean_text(value: Any, max_length: int) -> str:
    text = str(value or "")
    for original, replacement in _ASCII_REPLACEMENTS.items():
        text = text.replace(original, replacement)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = " ".join(text.split())
    if len(text) > max_length:
        cut = text[: max_length - 3]
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
        text = cut.rstrip(" ,.;:-") + "..."
    return text


def safe_url(value: Any) -> str:
    """The URL if it is a plain http(s) link the skin can safely open, else ''."""
    url = str(value or "").strip().split("#", 1)[0]
    if not url.lower().startswith(("https://", "http://")) or len(url) > 500:
        return ""
    if any(ch in _URL_FORBIDDEN for ch in url):
        return ""
    return url


def format_clock(moment: datetime) -> str:
    return moment.astimezone().strftime("%I:%M %p").lstrip("0")


def series_to_dict(
    series: PriceSeries | None, *, symbol: str, name: str, max_points: int
) -> dict[str, Any]:
    if series is None:
        return {
            "symbol": symbol,
            "name": clean_text(name, 40),
            "available": False,
            "priceText": "--",
            "changeText": "",
            "changePctText": "",
            "changePointsText": "",
            "direction": "flat",
            "points": [],
            "baseline": None,
        }

    change, change_pct = series.change, series.change_pct
    if change is None or change_pct is None:
        direction, change_text, change_pct_text, change_points_text = "flat", "", "", ""
    else:
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
        change_pct_text = f"{change_pct:+.2f}%"
        change_points_text = f"{change:+,.2f}"
        change_text = f"{change_points_text} ({change_pct_text})"

    points, baseline = normalize(
        series.closes, max_points=max_points, baseline=series.previous_close
    )
    return {
        "symbol": symbol,
        "name": clean_text(name, 40),
        "available": True,
        "price": round(series.price, 4),
        "priceText": f"{series.price:,.2f}",
        "changeText": change_text,
        "changePctText": change_pct_text,
        "changePointsText": change_points_text,
        "direction": direction,
        "points": points,
        "baseline": baseline,
    }


def story_to_dict(story: Story, series: PriceSeries | None, *, max_points: int) -> dict[str, Any]:
    return {
        "ticker": story.ticker,
        "company": clean_text(story.company, 40),
        "headline": clean_text(story.headline, 110),
        "summary": clean_text(story.summary, 320),
        "sentiment": story.sentiment,
        "source": clean_text(story.source, 40),
        "url": safe_url(story.url),
        "chart": series_to_dict(
            series, symbol=story.ticker, name=story.company, max_points=max_points
        )
        if series
        else None,
    }


def build_payload(
    *,
    status: str,
    status_text: str,
    message: str,
    stories: list[dict[str, Any]],
    indices: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "statusText": clean_text(status_text, 60),
        "message": clean_text(message, 300),
        "generatedAt": generated_at.isoformat(timespec="seconds"),
        "stories": stories,
        "indices": indices,
    }


def write_json_atomic(path: Path, payload: Any, attempts: int = 5) -> None:
    """Write via a temp file so readers never see a half-written document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="ascii")
    for attempt in range(attempts):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            # The skin may have the file open for a moment while reading it.
            if attempt == attempts - 1:
                raise
            time.sleep(0.2)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

"""Asks the AI to search the web for why a stock moved, and validates its answer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from .ai.base import AIProvider, AIReply, Citation
from .errors import AIError
from .market import PriceSeries

SENTIMENTS = ("positive", "negative", "neutral")

SYSTEM_PROMPT = (
    "You research stock price moves for a small desktop widget. Search the web for news "
    "from the last few days that explains the move. Use only facts from your search "
    "results. If nothing clearly explains the move, say so plainly instead of guessing. "
    "Never give investment advice. Your final answer must be a single JSON object and "
    "nothing else."
)


@dataclass(frozen=True)
class Story:
    ticker: str
    company: str
    headline: str
    summary: str
    sentiment: str
    source: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Story:
        return cls(**{field: str(data.get(field) or "") for field in cls.__dataclass_fields__})


def build_prompt(series: PriceSeries) -> str:
    pct = series.change_pct
    if pct is None:
        move = f"traded at {series.price:,.2f}"
    else:
        move = f"moved {'up' if pct >= 0 else 'down'} {abs(pct):.2f}% to {series.price:,.2f}"
    when = f"in the {series.session_date} trading session" if series.session_date else "today"

    return "\n".join(
        [
            f"{series.name} ({series.symbol}) {move} {when}.",
            "Search the web to find out why, then reply with JSON in exactly this shape:",
            '{"headline": "...", "summary": "...", "sentiment": "...", '
            '"source_name": "...", "source_url": "..."}',
            "",
            "- headline: at most 80 characters, naming the company and the reason for the move",
            "- summary: 2-3 plain sentences, at most 260 characters, on why the stock moved "
            "and why it matters",
            '- sentiment: "positive", "negative" or "neutral" for the stock',
            "- source_name and source_url: the single most relevant article you used",
        ]
    )


def research_story(provider: AIProvider, series: PriceSeries) -> Story:
    reply = provider.research(SYSTEM_PROMPT, build_prompt(series))
    return parse_story(reply, series)


def parse_story(reply: AIReply, series: PriceSeries) -> Story:
    data = _extract_json(reply.text)
    if not isinstance(data, dict):
        raise AIError(f"The AI's answer for {series.symbol} was not a JSON object")

    headline = str(data.get("headline") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not headline or not summary:
        raise AIError(f"The AI's answer for {series.symbol} was missing a headline or summary")

    sentiment = str(data.get("sentiment") or "").strip().lower()
    source, url = _pick_source(data, reply.citations)
    return Story(
        ticker=series.symbol,
        company=series.name,
        headline=headline,
        summary=summary,
        sentiment=sentiment if sentiment in SENTIMENTS else "neutral",
        source=source,
        url=url,
    )


def _pick_source(data: dict[str, Any], citations: tuple[Citation, ...]) -> tuple[str, str]:
    """Prefer a link the search actually returned over one the model wrote itself."""
    name = str(data.get("source_name") or "").strip()
    wanted = str(data.get("source_url") or "").strip()
    match = _matching_citation(wanted, name, citations)
    if match:
        verified = _comparable(wanted) == _comparable(match.url) or _domain(wanted) == _domain(
            match.url
        )
        label = name if verified and name else match.title or name or _domain(match.url)
        return label, match.url
    if wanted.lower().startswith(("https://", "http://")):
        return name or _domain(wanted), wanted
    return name, ""


def _matching_citation(
    wanted_url: str, source_name: str, citations: tuple[Citation, ...]
) -> Citation | None:
    if not citations:
        return None
    by_url = {_comparable(c.url): c for c in citations}
    if _comparable(wanted_url) in by_url:
        return by_url[_comparable(wanted_url)]
    domain = _domain(wanted_url)
    if domain:
        same_domain = next((c for c in citations if _domain(c.url) == domain), None)
        if same_domain:
            return same_domain
    folded = source_name.casefold()
    if folded:
        titled = next(
            (
                c
                for c in citations
                if c.title and (folded in c.title.casefold() or c.title.casefold() in folded)
            ),
            None,
        )
        if titled:
            return titled
    return citations[0]


def _comparable(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()


def _domain(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _extract_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise AIError("The AI response was not valid JSON")

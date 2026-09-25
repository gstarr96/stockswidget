from __future__ import annotations

import json

import pytest

from stocknews.ai import AIReply, Citation
from stocknews.errors import AIError
from stocknews.market import PriceSeries
from stocknews.research import build_prompt, parse_story

SERIES = PriceSeries(
    symbol="TWST",
    name="Twist Bioscience Corporation",
    price=184.03,
    previous_close=158.5,
    closes=(158.5, 184.03),
    session_date="2026-09-24",
)


def answer(**overrides) -> str:
    data = {
        "headline": "Twist jumps after raising guidance",
        "summary": "Twist raised its full-year revenue outlook.",
        "sentiment": "positive",
        "source_name": "Reuters",
        "source_url": "https://www.reuters.com/twist",
    }
    data.update(overrides)
    return json.dumps(data)


def test_prompt_describes_the_move_and_session():
    prompt = build_prompt(SERIES)

    assert "Twist Bioscience Corporation (TWST) moved up 16.11% to 184.03" in prompt
    assert "the 2026-09-24 trading session" in prompt


def test_prompt_for_a_falling_stock():
    falling = PriceSeries("GEN", "Gen Digital", 23.07, 26.23, (26.23, 23.07))

    assert "Gen Digital (GEN) moved down 12.05% to 23.07 today." in build_prompt(falling)


def test_parse_story_uses_model_source_when_it_was_cited():
    reply = AIReply(
        answer(),
        (
            Citation("Other", "https://x.com/a"),
            Citation("R", "https://www.reuters.com/twist?utm_source=openai"),
        ),
    )

    story = parse_story(reply, SERIES)

    assert story.ticker == "TWST"
    assert story.company == "Twist Bioscience Corporation"
    assert story.source == "Reuters"
    assert story.url == "https://www.reuters.com/twist?utm_source=openai"


def test_parse_story_replaces_uncited_url_with_first_citation():
    reply = AIReply(
        answer(source_url="https://made-up.example/story"),
        (Citation("CNBC", "https://www.cnbc.com/twist"),),
    )

    story = parse_story(reply, SERIES)

    assert story.url == "https://www.cnbc.com/twist"
    assert story.source == "CNBC"


def test_parse_story_keeps_the_model_url_when_the_search_returned_nothing():
    story = parse_story(AIReply(answer()), SERIES)

    assert story.url == "https://www.reuters.com/twist"
    assert story.source == "Reuters"


def test_parse_story_has_no_link_without_a_url():
    story = parse_story(AIReply(answer(source_url="")), SERIES)

    assert story.url == ""


def test_parse_story_accepts_code_fences_and_defaults_sentiment():
    text = "```json\n" + answer(sentiment="bullish") + "\n```"

    story = parse_story(AIReply(text), SERIES)

    assert story.sentiment == "neutral"


@pytest.mark.parametrize("text", ["no json here", "[1, 2]", answer(summary="")])
def test_unusable_answers_raise(text):
    with pytest.raises(AIError):
        parse_story(AIReply(text), SERIES)

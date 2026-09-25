from __future__ import annotations

import pytest

from stocknews.ai import AnthropicProvider, Citation, OpenAIProvider
from stocknews.errors import AIError, ConfigError, DataSourceError


def test_openai_sends_web_search_tool_and_parses_citations():
    sent = {}

    def fake_fetch(url, **kwargs):
        sent.update(url=url, **kwargs)
        return {
            "status": "completed",
            "output": [
                {"type": "web_search_call", "status": "completed"},
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"headline": "x"}',
                            "annotations": [
                                {"type": "url_citation", "url": "https://a.com/1", "title": "A"}
                            ],
                        }
                    ],
                },
            ],
        }

    reply = OpenAIProvider("sk", "gpt-5-mini", fetch=fake_fetch).research("sys", "prompt")

    assert sent["url"].endswith("/v1/responses")
    assert sent["body"]["tools"][0]["type"] == "web_search"
    assert sent["body"]["include"] == ["web_search_call.action.sources"]
    assert sent["headers"] == {"Authorization": "Bearer sk"}
    assert reply.text == '{"headline": "x"}'
    assert reply.citations == (Citation("A", "https://a.com/1"),)


def test_openai_reads_search_sources_when_there_are_no_inline_citations():
    def fake_fetch(url, **kwargs):
        return {
            "status": "completed",
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [
                            {
                                "type": "url",
                                "url": "https://www.reuters.com/twist",
                                "title": "Reuters",
                            }
                        ]
                    },
                },
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "{}", "annotations": []}],
                },
            ],
        }

    reply = OpenAIProvider("sk", "m", fetch=fake_fetch).research("s", "p")

    assert reply.citations == (Citation("Reuters", "https://www.reuters.com/twist"),)


def test_openai_without_answer_raises():
    def fake_fetch(url, **kwargs):
        return {"status": "incomplete", "output": [{"type": "web_search_call"}]}

    with pytest.raises(AIError, match="incomplete"):
        OpenAIProvider("sk", "m", fetch=fake_fetch).research("s", "p")


def test_anthropic_resumes_paused_turn_and_collects_citations():
    calls = []
    responses = [
        {
            "stop_reason": "pause_turn",
            "content": [
                {"type": "server_tool_use", "name": "web_search"},
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {"type": "web_search_result", "url": "https://s.com", "title": "S"}
                    ],
                },
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": '{"headline": '},
                {
                    "type": "text",
                    "text": '"x"}',
                    "citations": [{"url": "https://c.com", "title": "C"}],
                },
            ],
        },
    ]

    def fake_fetch(url, **kwargs):
        calls.append(kwargs["body"])
        return responses[len(calls) - 1]

    reply = AnthropicProvider("ak", "claude", fetch=fake_fetch).research("sys", "prompt")

    assert calls[0]["tools"][0]["name"] == "web_search"
    assert calls[1]["messages"][-1]["role"] == "assistant"
    assert reply.text == '{"headline": "x"}'
    assert reply.citations == (Citation("C", "https://c.com"),)


def test_anthropic_falls_back_to_search_results_when_nothing_is_cited():
    def fake_fetch(url, **kwargs):
        return {
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "web_search_tool_result",
                    "content": [
                        {"type": "web_search_result", "url": "https://s.com", "title": "S"}
                    ],
                },
                {"type": "text", "text": "{}"},
            ],
        }

    reply = AnthropicProvider("ak", "claude", fetch=fake_fetch).research("s", "p")

    assert reply.citations == (Citation("S", "https://s.com"),)


@pytest.mark.parametrize("provider_class", [OpenAIProvider, AnthropicProvider])
def test_rejected_key_becomes_config_error(provider_class):
    def fake_fetch(url, **kwargs):
        raise DataSourceError("HTTP 401: invalid key", status=401)

    with pytest.raises(ConfigError, match="rejected"):
        provider_class("bad", "model", fetch=fake_fetch).research("s", "p")

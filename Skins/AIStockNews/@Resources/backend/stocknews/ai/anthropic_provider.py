"""Anthropic Messages API with the server-side web search tool.

https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool
"""

from __future__ import annotations

from typing import Any

from ..errors import AIError, DataSourceError
from ..http import Fetch, request_json
from .base import AIProvider, AIReply, Citation, translate_error

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
WEB_SEARCH_TOOL = "web_search_20250305"
MAX_SEARCHES = 3
MAX_CONTINUATIONS = 2


class AnthropicProvider(AIProvider):
    name = "Anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        fetch: Fetch = request_json,
        timeout: float = 100,
        max_tokens: int = 1500,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fetch = fetch
        self._timeout = timeout
        self._max_tokens = max_tokens

    def research(self, system: str, prompt: str) -> AIReply:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        blocks: list[Any] = []
        for _ in range(MAX_CONTINUATIONS + 1):
            payload = self._send(system, messages)
            content = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(content, list):
                raise AIError("Anthropic returned an unexpected response")
            blocks.extend(content)
            # Long searches can pause mid-turn; sending the partial turn back resumes it.
            if payload.get("stop_reason") != "pause_turn":
                break
            messages = [*messages, {"role": "assistant", "content": content}]
        return parse_content(blocks)

    def _send(self, system: str, messages: list[dict[str, Any]]) -> Any:
        body = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
            "tools": [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": MAX_SEARCHES}],
        }
        try:
            return self._fetch(
                ANTHROPIC_MESSAGES_URL,
                method="POST",
                body=body,
                headers={"x-api-key": self._api_key, "anthropic-version": ANTHROPIC_VERSION},
                timeout=self._timeout,
                retries=1,
            )
        except DataSourceError as exc:
            raise translate_error(self.name, "[ai] anthropic_api_key", exc) from exc


def parse_content(blocks: list[Any]) -> AIReply:
    """Final answer text plus citations; search results are a fallback source list."""
    texts: list[str] = []
    cited: list[Citation] = []
    searched: list[Citation] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
            for citation in block.get("citations") or []:
                if isinstance(citation, dict) and citation.get("url"):
                    cited.append(Citation(str(citation.get("title") or ""), str(citation["url"])))
        elif block.get("type") == "web_search_tool_result":
            results = block.get("content")
            for result in results if isinstance(results, list) else []:
                if isinstance(result, dict) and result.get("url"):
                    searched.append(Citation(str(result.get("title") or ""), str(result["url"])))

    text = "".join(texts).strip()
    if not text:
        raise AIError("Anthropic returned no answer")
    return AIReply(text=text, citations=tuple(cited or searched))

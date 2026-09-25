"""OpenAI Responses API with the built-in web search tool.

https://platform.openai.com/docs/guides/tools-web-search
"""

from __future__ import annotations

from typing import Any

from ..errors import AIError, DataSourceError
from ..http import Fetch, request_json
from .base import AIProvider, AIReply, Citation, translate_error

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIProvider(AIProvider):
    name = "OpenAI"

    def __init__(
        self, api_key: str, model: str, fetch: Fetch = request_json, timeout: float = 100
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fetch = fetch
        self._timeout = timeout

    def research(self, system: str, prompt: str) -> AIReply:
        body = {
            "model": self._model,
            "instructions": system,
            "input": prompt,
            "tools": [{"type": "web_search", "search_context_size": "low"}],
            # JSON answers carry no inline citations, so ask for the pages that were searched.
            "include": ["web_search_call.action.sources"],
        }
        try:
            payload = self._fetch(
                OPENAI_RESPONSES_URL,
                method="POST",
                body=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
                retries=1,
            )
        except DataSourceError as exc:
            raise translate_error(self.name, "[ai] openai_api_key", exc) from exc
        return parse_response(payload)


def parse_response(payload: Any) -> AIReply:
    if not isinstance(payload, dict):
        raise AIError("OpenAI returned an unexpected response")
    error = payload.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else error
        raise AIError(f"OpenAI returned an error: {message}")

    texts: list[str] = []
    citations: list[Citation] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            sources = (item.get("action") or {}).get("sources") or []
            citations.extend(_citation(source) for source in sources if _citation(source))
            continue
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            texts.append(str(part.get("text") or ""))
            for note in part.get("annotations") or []:
                citation = _citation(note.get("url_citation") if isinstance(note, dict) else None)
                citations.append(citation or _citation(note))

    text = "".join(texts).strip()
    if not text:
        status = payload.get("status")
        raise AIError(f"OpenAI returned no answer (status: {status or 'unknown'})")
    return AIReply(text=text, citations=tuple(c for c in citations if c))


def _citation(entry: Any) -> Citation | None:
    if not isinstance(entry, dict) or not entry.get("url"):
        return None
    if entry.get("type") not in (None, "url", "url_citation"):
        return None
    return Citation(str(entry.get("title") or ""), str(entry["url"]))

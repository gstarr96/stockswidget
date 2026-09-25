"""Minimal JSON-over-HTTP client built on the standard library."""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import time
from collections.abc import Mapping
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .errors import DataSourceError

log = logging.getLogger(__name__)

USER_AGENT = f"AIStockNewsWidget/{__version__}"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_DELAY = 10.0

Fetch = Callable[..., Any]


def request_json(
    url: str,
    *,
    method: str = "GET",
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    body: Any = None,
    timeout: float = 20,
    retries: int = 2,
) -> Any:
    """Send a request and decode the JSON response.

    Raises DataSourceError on network failures, HTTP errors and invalid JSON.
    Error messages include the host but never the query string, which may hold secrets.
    """
    if params:
        url = f"{url}?{urlencode(params)}"
    host = urlsplit(url).netloc
    data = None if body is None else json.dumps(body).encode("utf-8")

    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        all_headers["Content-Type"] = "application/json"
    all_headers.update(headers or {})

    for attempt in range(retries + 1):
        request = Request(url, data=data, headers=all_headers, method=method)
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code in RETRY_STATUSES and attempt < retries:
                _sleep_before_retry(attempt, exc.headers.get("Retry-After"))
                continue
            raise DataSourceError(
                f"{host} returned HTTP {exc.code}: {_error_detail(exc)}", status=exc.code
            ) from exc
        except (URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            if attempt < retries:
                _sleep_before_retry(attempt)
                continue
            reason = getattr(exc, "reason", exc)
            raise DataSourceError(f"Could not reach {host}: {reason}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise DataSourceError(f"{host} returned a response that is not valid JSON") from exc

    raise AssertionError("unreachable")


def _sleep_before_retry(attempt: int, retry_after: str | None = None) -> None:
    delay = 1.5 * (2**attempt)
    if retry_after:
        with contextlib.suppress(ValueError):
            delay = float(retry_after)
    delay = min(delay, MAX_RETRY_DELAY)
    log.debug("Retrying in %.1fs", delay)
    time.sleep(delay)


def _error_detail(exc: HTTPError) -> str:
    try:
        text = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return exc.reason or "no details"
    try:
        payload = json.loads(text)
    except ValueError:
        return text.strip()[:200] or str(exc.reason)
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:200]
        if isinstance(error, str):
            return error[:200]
        chart_error = (payload.get("chart") or {}).get("error")
        if isinstance(chart_error, dict) and chart_error.get("description"):
            return str(chart_error["description"])[:200]
    return text.strip()[:200]

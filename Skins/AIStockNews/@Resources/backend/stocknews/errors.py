"""Exception hierarchy. Messages are shown to the user, so keep them actionable."""

from __future__ import annotations


class StockNewsError(Exception):
    """Base class for expected failures."""


class ConfigError(StockNewsError):
    """Settings are missing or invalid, or an API key was rejected."""


class DataSourceError(StockNewsError):
    """A remote API could not be reached or returned an unusable response."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class MarketDataError(DataSourceError):
    """Price data for a symbol is unavailable."""

    def __init__(self, message: str, status: int | None = None, not_found: bool = False) -> None:
        super().__init__(message, status)
        self.not_found = not_found


class AIError(StockNewsError):
    """The AI provider failed or returned something unusable."""

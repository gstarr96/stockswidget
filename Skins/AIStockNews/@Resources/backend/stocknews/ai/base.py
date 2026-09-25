from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..errors import AIError, ConfigError, DataSourceError


@dataclass(frozen=True)
class Citation:
    title: str
    url: str


@dataclass(frozen=True)
class AIReply:
    text: str
    citations: tuple[Citation, ...] = field(default_factory=tuple)


class AIProvider(ABC):
    """A chat model that can search the web before answering."""

    name: str = "AI"

    @abstractmethod
    def research(self, system: str, prompt: str) -> AIReply:
        """Answer ``prompt`` using the provider's web search tool.

        Returns the model's final text plus the web pages it cited.
        """


def translate_error(provider: str, key_setting: str, exc: DataSourceError) -> Exception:
    """Map HTTP failures to messages a widget user can act on."""
    if exc.status in (401, 403):
        return ConfigError(
            f"{provider} rejected the request ({exc}). Check {key_setting} in config.ini."
        )
    if exc.status == 404:
        return ConfigError(f"{provider} does not recognize the configured model: {exc}")
    if exc.status == 429:
        return AIError(f"{provider} rate limit or quota reached. Check your plan and billing.")
    return AIError(f"{provider} request failed: {exc}")

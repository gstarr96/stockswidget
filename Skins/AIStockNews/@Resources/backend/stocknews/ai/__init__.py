"""AI providers. Add a new one by subclassing AIProvider and registering it here."""

from __future__ import annotations

from ..config import Settings
from ..errors import ConfigError
from .anthropic_provider import AnthropicProvider
from .base import AIProvider, AIReply, Citation
from .openai_provider import OpenAIProvider

__all__ = [
    "AIProvider",
    "AIReply",
    "AnthropicProvider",
    "Citation",
    "OpenAIProvider",
    "create_provider",
]


def create_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "openai":
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if settings.ai_provider == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    raise ConfigError(f"Unknown AI provider '{settings.ai_provider}'")

"""Provider registry for dynamic LLM provider management."""
from __future__ import annotations

from typing import Type

from .base import LLMProvider, LLMConfig


# Global registry of providers
_PROVIDERS: dict[str, Type[LLMProvider]] = {}


def register_provider(name: str, provider_class: Type[LLMProvider]) -> None:
    """Register a new LLM provider.

    Usage:
        register_provider("my_provider", MyProviderClass)

    Then use with:
        config = LLMConfig(provider_name="my_provider", api_key="...")
        provider = get_provider(config)
    """
    _PROVIDERS[name.lower()] = provider_class


def get_provider(config: LLMConfig) -> LLMProvider:
    """Get a provider instance from config.

    Args:
        config: LLMConfig with provider_name set

    Returns:
        An initialized LLMProvider instance

    Raises:
        ValueError: If provider_name is not registered
    """
    name = config.provider_name.lower()
    if name not in _PROVIDERS:
        available = ", ".join(_PROVIDERS.keys()) if _PROVIDERS else "(none registered)"
        raise ValueError(
            f"Unknown provider: {name}. Available: {available}"
        )
    return _PROVIDERS[name](config)


def list_providers() -> list[str]:
    """List all registered provider names."""
    return list(_PROVIDERS.keys())


# Auto-register built-in providers on import
def _register_builtins() -> None:
    """Register all built-in providers."""
    from .providers import (
        AnthropicProvider,
        OpenAIProvider,
        OpenRouterProvider,
        XAIProvider,
        VultrProvider,
    )

    register_provider("anthropic", AnthropicProvider)
    register_provider("openai", OpenAIProvider)
    register_provider("openrouter", OpenRouterProvider)
    register_provider("xai", XAIProvider)
    register_provider("vultr", VultrProvider)


# Register on module load
_register_builtins()

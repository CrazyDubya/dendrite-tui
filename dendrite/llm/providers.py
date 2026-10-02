"""Concrete LLM provider implementations.

Each provider follows the same pattern:
1. Set DEFAULT_MODEL and BASE_URL
2. Implement complete() for full responses
3. Implement stream() for streaming responses

To add a new provider, copy any existing one and adjust the API specifics.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from .base import LLMProvider, LLMConfig, Message, StreamChunk, Role


def _ensure_httpx() -> None:
    """Ensure httpx is available."""
    if not HTTPX_AVAILABLE:
        raise ImportError(
            "httpx is required for LLM providers. "
            "Install with: pip install httpx"
        )


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider.

    Env var: ANTHROPIC_API_KEY
    Models: claude-3-5-sonnet-20241022, claude-3-opus-20240229, etc.
    """

    DEFAULT_MODEL = "claude-sonnet-4-20250514"
    BASE_URL = "https://api.anthropic.com"

    async def complete(self, messages: list[Message]) -> str:
        _ensure_httpx()

        # Anthropic uses a separate system parameter
        system_msg = None
        other_messages = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system_msg = m.content
            else:
                other_messages.append({"role": m.role.value, "content": m.content})

        payload = {
            "model": self.model,
            "max_tokens": self.config.max_tokens,
            "messages": other_messages,
        }
        if system_msg:
            payload["system"] = system_msg

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._get_base_url()}/v1/messages",
                headers={
                    "x-api-key": self.config.get_api_key(),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]

    async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
        _ensure_httpx()

        system_msg = None
        other_messages = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system_msg = m.content
            else:
                other_messages.append({"role": m.role.value, "content": m.content})

        payload = {
            "model": self.model,
            "max_tokens": self.config.max_tokens,
            "messages": other_messages,
            "stream": True,
        }
        if system_msg:
            payload["system"] = system_msg

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._get_base_url()}/v1/messages",
                headers={
                    "x-api-key": self.config.get_api_key(),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data["type"] == "content_block_delta":
                            yield StreamChunk(
                                content=data["delta"].get("text", ""),
                                is_final=False,
                            )
                        elif data["type"] == "message_stop":
                            yield StreamChunk(content="", is_final=True)


class OpenAIProvider(LLMProvider):
    """OpenAI API provider.

    Env var: OPENAI_API_KEY
    Models: gpt-4o, gpt-4-turbo, gpt-3.5-turbo, etc.
    """

    DEFAULT_MODEL = "gpt-4o"
    BASE_URL = "https://api.openai.com"

    async def complete(self, messages: list[Message]) -> str:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "stream": True,
                },
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        finish = data["choices"][0].get("finish_reason")
                        if content or finish:
                            yield StreamChunk(
                                content=content,
                                is_final=finish is not None,
                                finish_reason=finish,
                            )


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider - access many models through one API.

    Env var: OPENROUTER_API_KEY
    Models: anthropic/claude-3-5-sonnet, openai/gpt-4o, meta-llama/llama-3-70b, etc.

    OpenRouter gives you access to 100+ models with a single API key.
    See https://openrouter.ai/models for the full list.
    """

    DEFAULT_MODEL = "anthropic/claude-3-5-sonnet"
    BASE_URL = "https://openrouter.ai/api"

    async def complete(self, messages: list[Message]) -> str:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self.config.extra.get("referer", "https://dendrite.app"),
                    "X-Title": self.config.extra.get("title", "Dendrite"),
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self.config.extra.get("referer", "https://dendrite.app"),
                    "X-Title": self.config.extra.get("title", "Dendrite"),
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "stream": True,
                },
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        finish = data["choices"][0].get("finish_reason")
                        if content or finish:
                            yield StreamChunk(
                                content=content,
                                is_final=finish is not None,
                                finish_reason=finish,
                            )


class XAIProvider(LLMProvider):
    """xAI (Grok) API provider.

    Env var: XAI_API_KEY
    Models: grok-beta, grok-2, etc.

    xAI uses an OpenAI-compatible API format.
    """

    DEFAULT_MODEL = "grok-beta"
    BASE_URL = "https://api.x.ai"

    async def complete(self, messages: list[Message]) -> str:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "stream": True,
                },
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        finish = data["choices"][0].get("finish_reason")
                        if content or finish:
                            yield StreamChunk(
                                content=content,
                                is_final=finish is not None,
                                finish_reason=finish,
                            )


class VultrProvider(LLMProvider):
    """Vultr Serverless Inference API provider.

    Env var: VULTR_API_KEY
    Models: See https://www.vultr.com/docs/vultr-inference/

    Vultr uses an OpenAI-compatible API format.
    You can run various open models on Vultr's infrastructure.
    """

    DEFAULT_MODEL = "llama2-13b-chat-Q5_K_M"
    BASE_URL = "https://api.vultrinference.com"

    async def complete(self, messages: list[Message]) -> str:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
        _ensure_httpx()

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self._get_base_url()}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.config.get_api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": self._format_messages(messages),
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "stream": True,
                },
                timeout=60.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        data = json.loads(line[6:])
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        finish = data["choices"][0].get("finish_reason")
                        if content or finish:
                            yield StreamChunk(
                                content=content,
                                is_final=finish is not None,
                                finish_reason=finish,
                            )


# =============================================================================
# ADDING A NEW PROVIDER - TEMPLATE
# =============================================================================
#
# To add a new provider (e.g., "mistral", "together", "groq", etc.):
#
# 1. Copy this template:
#
# class MyNewProvider(LLMProvider):
#     """Description of the provider.
#
#     Env var: MY_PROVIDER_API_KEY
#     Models: list some models
#     """
#
#     DEFAULT_MODEL = "the-default-model"
#     BASE_URL = "https://api.myprovider.com"
#
#     async def complete(self, messages: list[Message]) -> str:
#         # Implement non-streaming completion
#         pass
#
#     async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
#         # Implement streaming
#         pass
#
# 2. Register it in registry.py:
#    register_provider("myprovider", MyNewProvider)
#
# 3. Add the env var to base.py LLMConfig.get_api_key()
#
# That's it! The provider is now available everywhere.
# =============================================================================

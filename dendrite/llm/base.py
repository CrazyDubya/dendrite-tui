"""Base classes and interfaces for LLM providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional
import os


class Role(Enum):
    """Message roles in a conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A single message in a conversation."""
    role: Role
    content: str

    @classmethod
    def system(cls, content: str) -> Message:
        return cls(Role.SYSTEM, content)

    @classmethod
    def user(cls, content: str) -> Message:
        return cls(Role.USER, content)

    @classmethod
    def assistant(cls, content: str) -> Message:
        return cls(Role.ASSISTANT, content)


@dataclass
class StreamChunk:
    """A chunk of streamed response."""
    content: str
    is_final: bool = False
    finish_reason: Optional[str] = None


@dataclass
class LLMConfig:
    """Configuration for an LLM provider.

    The beauty: every provider uses the same config structure.
    Just change provider_name and optionally model.
    """
    provider_name: str  # "anthropic", "openai", "openrouter", "xai", "vultr"
    api_key: Optional[str] = None  # Falls back to env var
    model: Optional[str] = None  # Provider-specific default if None
    base_url: Optional[str] = None  # For custom endpoints
    max_tokens: int = 1024
    temperature: float = 0.7
    extra: dict = field(default_factory=dict)  # Provider-specific options

    def get_api_key(self) -> str:
        """Get API key from config or environment."""
        if self.api_key:
            return self.api_key

        env_vars = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "xai": "XAI_API_KEY",
            "vultr": "VULTR_API_KEY",
        }

        env_var = env_vars.get(self.provider_name.lower())
        if env_var:
            key = os.environ.get(env_var)
            if key:
                return key

        # Also check generic key
        generic = os.environ.get("LLM_API_KEY")
        if generic:
            return generic

        raise ValueError(
            f"No API key found for {self.provider_name}. "
            f"Set {env_var} environment variable or pass api_key in config."
        )


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    To add a new provider:
    1. Create a class that inherits from LLMProvider
    2. Implement complete() and stream()
    3. Register it with register_provider()

    That's it. Three steps to support any LLM.
    """

    # Default model for this provider (override in subclass)
    DEFAULT_MODEL: str = ""

    # Base URL for the API (override in subclass)
    BASE_URL: str = ""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.model = config.model or self.DEFAULT_MODEL

    @abstractmethod
    async def complete(self, messages: list[Message]) -> str:
        """Complete a conversation and return the full response.

        Args:
            messages: List of messages in the conversation

        Returns:
            The assistant's response as a string
        """
        pass

    @abstractmethod
    async def stream(self, messages: list[Message]) -> AsyncIterator[StreamChunk]:
        """Stream a conversation response.

        Args:
            messages: List of messages in the conversation

        Yields:
            StreamChunk objects as they arrive
        """
        pass

    def _format_messages(self, messages: list[Message]) -> list[dict]:
        """Convert Message objects to API format."""
        return [{"role": m.role.value, "content": m.content} for m in messages]

    def _get_base_url(self) -> str:
        """Get the base URL for API requests."""
        return self.config.base_url or self.BASE_URL


# Dendrite-specific prompts for idea expansion
DENDRITE_SYSTEM_PROMPT = """You are a creative thinking partner helping to develop and expand ideas.

When asked to "grow" an idea:
- Explore 2-3 different directions the idea could develop
- Be concise but insightful
- Suggest concrete next steps or questions to explore
- Format as a bulleted list for easy reading

When asked to "branch" from an idea:
- Suggest related but distinct ideas
- Think laterally, not just linearly
- Keep each suggestion brief (1-2 sentences)

When asked to "question" an idea:
- Challenge assumptions
- Identify potential weaknesses
- Suggest what's missing

Always be helpful, concise, and thought-provoking."""


def make_grow_prompt(node_content: str, path_to_root: list[str]) -> list[Message]:
    """Create a prompt for growing an idea."""
    context = " → ".join(reversed(path_to_root)) if path_to_root else "root"

    return [
        Message.system(DENDRITE_SYSTEM_PROMPT),
        Message.user(
            f"I'm developing this idea tree:\n\n"
            f"Path: {context}\n\n"
            f"Current idea: {node_content}\n\n"
            f"Help me grow this idea. What directions could it develop? "
            f"Give me 2-3 concrete possibilities, each as a potential branch."
        )
    ]


def make_branch_prompt(node_content: str, siblings: list[str]) -> list[Message]:
    """Create a prompt for suggesting new branches."""
    sibling_text = "\n".join(f"- {s}" for s in siblings) if siblings else "(none yet)"

    return [
        Message.system(DENDRITE_SYSTEM_PROMPT),
        Message.user(
            f"Current idea: {node_content}\n\n"
            f"Existing branches:\n{sibling_text}\n\n"
            f"Suggest 2-3 NEW branch ideas that are different from the existing ones. "
            f"Each should be a distinct direction to explore."
        )
    ]


def make_question_prompt(node_content: str, history_summary: str) -> list[Message]:
    """Create a prompt for questioning an idea."""
    return [
        Message.system(DENDRITE_SYSTEM_PROMPT),
        Message.user(
            f"Idea: {node_content}\n\n"
            f"History: {history_summary}\n\n"
            f"Question this idea. What assumptions am I making? "
            f"What's weak? What am I missing?"
        )
    ]

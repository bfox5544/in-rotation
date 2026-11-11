"""What the assistant needs from a language model provider. Only gemini.py knows about Gemini;
another provider is one more module implementing ChatProvider."""
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict              # JSON Schema for the arguments


@dataclass(frozen=True)
class Turn:
    role: Literal["user", "assistant"]
    text: str


@dataclass
class Reply:
    text: str
    calls: int                    # model requests this reply took (tool rounds + the final answer)
    truncated: bool = False       # stopped at the output token limit


# The provider runs the tool loop, since how tool calls and results are passed back is provider-specific.
RunTool = Callable[[str, dict], Awaitable[dict]]


class ProviderError(Exception):
    """kind: 'quota' (daily quota used up: don't retry until it resets), 'rate' (per-minute limit),
    'unavailable' (network, timeout, server error), 'config' (bad key or model), 'blocked' (safety),
    'invalid' (an answer we can't use). `calls` is how many requests were made before failing."""

    def __init__(self, kind: str, message: str, calls: int = 0, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.calls, self.retry_after = kind, calls, retry_after


class ChatProvider(Protocol):
    model: str

    async def respond(self, system: str, history: list[Turn], tools: list[ToolSpec], run_tool: RunTool,
                      max_calls: int) -> Reply: ...


@lru_cache
def get_provider() -> ChatProvider | None:
    """The configured provider, or None when no key is set (the assistant then reports itself off)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    from .gemini import GeminiProvider
    return GeminiProvider(key, model=os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite")

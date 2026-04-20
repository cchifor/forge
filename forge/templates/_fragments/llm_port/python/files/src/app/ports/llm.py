"""LLM provider port — the capability contract every adapter implements.

Adapters live under ``app/adapters/llm/<provider>.py`` and register
themselves with the dependency container based on the
``LLM_PROVIDER`` environment variable. The rest of the application
depends on this Protocol.

See ``docs/architecture-decisions/ADR-002-ports-and-adapters.md`` for
the why.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class LlmMessage:
    """One message in a chat conversation.

    ``role`` is ``system`` / ``user`` / ``assistant`` / ``tool``.
    ``content`` is the text body. ``tool_calls`` lists any tool
    invocations emitted by the model on this turn. ``name`` is used
    for ``role=tool`` to identify which tool produced this message.
    """

    role: str
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class LlmTool:
    """Tool declaration passed to the model.

    Matches the OpenAI + Anthropic + Bedrock schemas. ``input_schema``
    is the JSON Schema for the tool's arguments.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class LlmStreamChunk:
    """One chunk from a streaming completion."""

    text_delta: str = ""
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class LlmProviderPort(Protocol):
    """LLM provider surface used by the agent loop.

    Adapters implement the two methods below. Streaming is the primary
    API; non-streaming is a convenience that internally consumes the
    stream.
    """

    async def complete_stream(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LlmStreamChunk]:
        """Stream a chat completion as a sequence of deltas."""

    async def complete(
        self,
        *,
        model: str,
        messages: list[LlmMessage],
        tools: list[LlmTool] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LlmMessage:
        """Non-streaming convenience that returns the assembled assistant message."""

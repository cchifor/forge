"""Typed event envelope for the /ws/agent WebSocket.

Clients receive a stream of one-JSON-object-per-frame messages, each with a
``type`` discriminator. Forward-compatible by design: new event types can
be added without breaking older clients (they ignore unknown types).

Shape chosen to match the pydantic-ai reference protocol so a future
`agent` feature can stream model output with minimal rework.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class _Base(BaseModel):
    # Stable event id for client-side idempotency.
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime = Field(default_factory=_now)


class ConversationCreated(_Base):
    type: Literal["conversation_created"] = "conversation_created"
    conversation_id: uuid.UUID


class UserPromptReceived(_Base):
    type: Literal["user_prompt"] = "user_prompt"
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    content: str


class TextDelta(_Base):
    """Incremental text from the assistant. Concat ``delta`` fields in order
    to reconstruct the full response."""

    type: Literal["text_delta"] = "text_delta"
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    delta: str


class ToolCallStarted(_Base):
    type: Literal["tool_call"] = "tool_call"
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    tool_call_id: uuid.UUID
    tool_name: str
    arguments: dict[str, Any]


class ToolResult(_Base):
    type: Literal["tool_result"] = "tool_result"
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    tool_call_id: uuid.UUID
    tool_name: str
    result: Any
    error: str | None = None


class AgentStatus(_Base):
    """Lifecycle signal. "thinking" at start of each turn, "done" at end,
    "error" on failure. Clients drive UI state off this."""

    type: Literal["agent_status"] = "agent_status"
    conversation_id: uuid.UUID
    status: Literal["thinking", "done", "error"]
    detail: str | None = None


class ErrorEvent(_Base):
    type: Literal["error"] = "error"
    conversation_id: uuid.UUID | None = None
    message: str


AgentEvent = (
    ConversationCreated
    | UserPromptReceived
    | TextDelta
    | ToolCallStarted
    | ToolResult
    | AgentStatus
    | ErrorEvent
)

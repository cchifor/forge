"""Typed event envelope for the /ws/agent WebSocket.

Clients receive a stream of one-JSON-object-per-frame messages, each
carrying a discriminator field. Forward-compatible by design: new event
types can be added without breaking older clients (they ignore unknown
discriminators).

Shape chosen to match the pydantic-ai reference protocol so a future
``agent`` feature can stream model output with minimal rework.

Discriminator transition
------------------------
Historically the wire used ``type`` as the discriminator
(``{"type": "text_delta", "delta": "..."}``). The repo-wide canvas
``AgUiEvent`` codegen uses ``kind`` instead, and we are converging the
WebSocket frames onto the same field for a single source of truth.

To avoid breaking existing clients (Vue/Svelte/Flutter chat shims and
contract tests pinned to ``type``) the serializer emits BOTH fields for
one release: every frame carries ``"type": "<slug>"`` AND
``"kind": "<slug>"`` with byte-identical values. The validator likewise
accepts either as input. The compat alias is documented for removal in
the next minor release once known consumers have migrated to ``kind``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_serializer, model_validator


def _now() -> datetime:
    return datetime.now(UTC)


class _Base(BaseModel):
    # Stable event id for client-side idempotency.
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime = Field(default_factory=_now)

    @model_validator(mode="before")
    @classmethod
    def _accept_kind_alias(cls, data: Any) -> Any:
        """Accept the canonical ``kind`` discriminator as an alias for ``type``.

        Wire frames in flight during the transition may arrive with
        either key; normalise to ``type`` so the existing ``Literal``
        discriminator on each subclass keeps validating.

        If BOTH keys are present they must agree byte-for-byte — a
        drifted frame (``{"type": "tool_call", "kind": "text_delta"}``)
        is ambiguous and must be rejected rather than silently routed
        to one discriminator. Letting the mismatch through would mask
        a real bug somewhere upstream (a serializer pinning ``type``
        out of sync with the canvas ``kind``) for one whole release,
        exactly the window Initiative #4 is trying to close.
        """
        if isinstance(data, dict):
            has_type = "type" in data
            has_kind = "kind" in data
            if has_type and has_kind and data["type"] != data["kind"]:
                raise ValueError(
                    "AgentEvent frame has mismatched `type` and `kind` "
                    f"discriminators (type={data['type']!r}, "
                    f"kind={data['kind']!r}). During the type -> kind "
                    "transition both keys must carry the same value."
                )
            if has_kind and not has_type:
                data = {**data, "type": data["kind"]}
        return data

    @model_serializer(mode="wrap")
    def _emit_kind_alias(self, handler: Any) -> Any:
        """Emit both ``type`` (legacy) and ``kind`` (canonical) on the wire.

        Mirrors the canvas ``AgUiEvent`` codegen which already uses
        ``kind`` as the discriminator field. Removing ``type`` is a
        separate, breaking change scheduled for the next minor release.
        """
        data = handler(self)
        if isinstance(data, dict) and "type" in data:
            data["kind"] = data["type"]
        return data


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

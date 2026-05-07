"""Pydantic schemas for conversation persistence.

These are the on-the-wire shapes — request/response models for any future
/api/v1/conversations router and the canonical types the agent_streaming
WebSocket serializes over. Keep them minimal; add domain logic in services,
not schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolCall(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None
    status: ToolCallStatus = ToolCallStatus.PENDING
    error: str | None = None
    duration_ms: float | None = None
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    metadata_json: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class Conversation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    metadata_json: dict[str, Any] | None = None
    archived_at: datetime | None = None
    messages: list[Message] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    title: str = "New conversation"
    metadata_json: dict[str, Any] | None = None


class MessageCreate(BaseModel):
    role: MessageRole = MessageRole.USER
    content: str
    metadata_json: dict[str, Any] | None = None

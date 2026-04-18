"""SQLAlchemy models for conversation persistence.

A ``Conversation`` groups ``Message`` rows in insert order. Each ``Message``
carries a role (user / assistant / system / tool) and optional ``ToolCall``
children recording any tool invocations the assistant made while producing
that message. Deliberately simpler than the pydantic-ai reference
implementation — no files/attachments (file_upload feature owns those) and
no per-message token accounting (add it in the repo layer if you need it).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.data.models.base import JSON_TYPE, Base
from service.repository.mixins import TenantMixin, TimestampMixin, UserOwnedMixin


class Conversation(Base, TenantMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="New conversation")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_conversations_customer_created", "customer_id", "created_at"),
        Index("ix_conversations_customer_user", "customer_id", "user_id"),
    )


class Message(Base, TenantMixin, TimestampMixin):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Discriminator: "user" | "assistant" | "system" | "tool"
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Free-form metadata (provider, model, finish_reason, ...).
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_customer_id", "customer_id"),
    )


class ToolCall(Base, TenantMixin, TimestampMixin):
    __tablename__ = "conversation_tool_calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)
    # "pending" | "succeeded" | "failed"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(nullable=True)

    message: Mapped[Message] = relationship(back_populates="tool_calls")

    __table_args__ = (
        Index("ix_tool_calls_message", "message_id"),
        Index("ix_tool_calls_tool_name", "tool_name"),
    )

"""SQLAlchemy model for chat file attachments.

A ``ChatFile`` is a user-uploaded binary associated with a ``Message`` (so
the conversation log carries the full context of what was sent). For local
storage the ``storage_path`` is a relative filesystem path under
``UPLOAD_DIR``; for S3 it's the object key.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.data.models.base import Base
from service.repository.mixins import TenantMixin, TimestampMixin, UserOwnedMixin


class ChatFile(Base, TenantMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "chat_files"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Nullable — a file can be uploaded before being attached to a message.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Local-storage path (relative to UPLOAD_DIR) or S3 key.
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional extracted text / OCR output. Populated lazily by a tool.
    parsed_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    message = relationship("Message", foreign_keys=[message_id], lazy="select")

    __table_args__ = (
        Index("ix_chat_files_message", "message_id"),
        Index("ix_chat_files_customer_user", "customer_id", "user_id"),
    )

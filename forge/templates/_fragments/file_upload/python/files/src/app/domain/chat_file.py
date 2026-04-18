"""Pydantic schemas for chat file attachments."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatFile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    message_id: uuid.UUID | None
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    parsed_content: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatFileUploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int

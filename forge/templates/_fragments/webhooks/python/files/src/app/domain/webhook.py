"""Pydantic schemas for the webhook API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Webhook(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    events: list[str]
    is_active: bool
    extra_headers: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class WebhookCreate(BaseModel):
    name: str
    url: HttpUrl
    events: list[str] = Field(default_factory=list)
    extra_headers: dict[str, Any] | None = None


class WebhookDeliveryResult(BaseModel):
    webhook_id: uuid.UUID
    status_code: int | None
    ok: bool
    error: str | None = None
    duration_ms: int

"""Webhook registry model.

A ``Webhook`` is a customer-scoped outbound endpoint that receives
HMAC-SHA256-signed payloads when events fire. ``events`` is a list of
event-name globs (``"item.*"`` matches ``"item.created"`` etc.); empty
means "all events".
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import JSON_TYPE, Base
from service.repository.mixins import TenantMixin, TimestampMixin, UserOwnedMixin


class Webhook(Base, TenantMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Secret used to HMAC-sign outgoing payloads. Clients verify on receipt.
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    # JSON array of event-name patterns; empty array = subscribe to everything.
    events: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Optional headers merged into the outbound request (e.g. {"X-Source": "forge"}).
    extra_headers: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE, nullable=True)

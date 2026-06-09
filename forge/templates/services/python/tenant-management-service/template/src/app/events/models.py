"""Domain event definitions.

Each event is a frozen Pydantic model that captures the minimal data needed
for downstream consumers to react.  Events are serialized to JSON and
stored in the outbox table, then relayed to Valkey Streams.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """Base class for all domain events."""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_type: str  # set by subclass
    occurred_at: str = Field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())
    # Routing key for Valkey Stream (e.g. "tms.events")
    stream: str = "tms.events"


class TenantProvisioned(DomainEvent):
    event_type: Literal["tenant.provisioned"] = "tenant.provisioned"
    tenant_id: str
    slug: str
    hostname: str
    tier: str
    realm_name: str
    admin_email: str


class TenantSuspended(DomainEvent):
    event_type: Literal["tenant.suspended"] = "tenant.suspended"
    tenant_id: str
    slug: str
    hostname: str


class TenantReactivated(DomainEvent):
    event_type: Literal["tenant.reactivated"] = "tenant.reactivated"
    tenant_id: str
    slug: str
    hostname: str
    tier: str

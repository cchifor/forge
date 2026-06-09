"""Domain event definitions and event bus infrastructure.

Events are published to Valkey Streams via the transactional outbox pattern:
the event is written to the ``outbox`` DB table in the same transaction as
the domain change, then a background relay picks up unpublished rows and
pushes them to Valkey Streams.  This guarantees at-least-once delivery
without 2PC or distributed transactions.
"""

from app.events.models import DomainEvent, TenantProvisioned, TenantReactivated, TenantSuspended
from app.events.outbox import OutboxRelay
from app.events.publisher import EventPublisher

__all__ = [
    "DomainEvent",
    "TenantProvisioned",
    "TenantSuspended",
    "TenantReactivated",
    "EventPublisher",
    "OutboxRelay",
]

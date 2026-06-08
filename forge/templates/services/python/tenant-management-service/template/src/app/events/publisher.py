"""Transactional outbox — write events to a DB table in the same transaction.

The ``EventPublisher`` is injected into services alongside the UoW.  It
writes events to the ``outbox`` table using the same SQLAlchemy session,
so the event is guaranteed to be committed atomically with the domain
change.  The ``OutboxRelay`` background task picks up unpublished rows
and streams them to Valkey.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.models import DomainEvent

logger = logging.getLogger(__name__)


class EventPublisher:
    """Writes domain events to the outbox table within the current session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, event: DomainEvent) -> None:
        """Insert an event into the outbox (same transaction as the caller)."""
        await self._session.execute(
            text(
                "INSERT INTO outbox (event_id, event_type, stream, payload, published) "
                "VALUES (:event_id, :event_type, :stream, :payload, FALSE)"
            ),
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "stream": event.stream,
                "payload": event.model_dump_json(),
            },
        )
        logger.debug("Outbox: queued %s (id=%s)", event.event_type, event.event_id)

"""Transactional outbox wiring.

The :class:`weld.events.OutboxStore` lets repositories append rows to
the ``outbox`` table inside the same transaction as their domain
writes. A background :class:`weld.events.OutboxRelay` task polls the
table and republishes pending rows through the configured
:class:`EventBus`. Marking ``published_at`` is what removes a row from
the relay's working set.

The relay is started + stopped from the FastAPI lifespan (see
``app/core/lifecycle.py``); the store is request-scoped so handlers
hand it the active ``AsyncSession`` and stay inside the unit of work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weld.events import EventBus, OutboxRelay, OutboxStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def build_outbox_store(session: AsyncSession) -> OutboxStore:
    return OutboxStore(session=session)


def build_outbox_relay(engine: AsyncEngine, bus: EventBus, poll_interval_s: float) -> OutboxRelay:
    return OutboxRelay(engine=engine, bus=bus, poll_interval_s=poll_interval_s)

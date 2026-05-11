"""Build the service's :class:`weld.events.EventBus` from settings.

The transport is read from ``settings.events.bus``; the dotted-path
matches the ``events.bus`` forge option so generated services line up
with their forge.yaml. ``postgres_notify`` is the default platform
transport — Postgres ``LISTEN/NOTIFY`` on the ``domain_events`` channel.
``memory`` is for tests and local dev.

The Dishka container scopes a single ``EventBus`` to the application
lifetime (see :mod:`app.core.ioc.infra`); handlers receive it via
``Depends`` or directly through the request-scoped DI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weld.events import (
    CloudEvent,
    EventBus,
    PostgresNotifyBus,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from app.core.config.domain import Settings


async def build_event_bus(settings: Settings, engine: AsyncEngine) -> EventBus:
    transport = settings.events.bus
    if transport == "postgres_notify":
        bus = PostgresNotifyBus(
            engine=engine,
            channel=settings.events.channel,
        )
        await bus.start()
        return bus
    if transport == "memory":
        from weld.events.bus import InMemoryEventBus

        return InMemoryEventBus()
    raise ValueError(f"Unsupported events.bus transport: {transport!r}")


async def publish(bus: EventBus, event: CloudEvent) -> None:
    """Thin wrapper so call sites don't import :class:`EventBus` directly."""

    await bus.publish(event)

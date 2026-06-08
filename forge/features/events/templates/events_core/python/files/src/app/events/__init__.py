"""Service-local CloudEvents wiring (vendored, weld-free).

Re-exports the CloudEvents envelope, the :class:`EventBus` protocol and
its transports, plus the bus factory and publish helper so handlers can::

    from app.events import CloudEvent, build_event_bus, publish

Swap the transport in :mod:`app.events.bus` if/when this service moves
off Postgres ``LISTEN/NOTIFY`` — the rest of the app depends only on the
:class:`EventBus` protocol.
"""

from __future__ import annotations

from app.events.bus import (
    BackpressureError,
    EventBus,
    InMemoryEventBus,
    PostgresNotifyBus,
    build_event_bus,
    publish,
)
from app.events.envelope import CloudEvent

__all__ = [
    "BackpressureError",
    "CloudEvent",
    "EventBus",
    "InMemoryEventBus",
    "PostgresNotifyBus",
    "build_event_bus",
    "publish",
]

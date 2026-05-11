"""Service-local CloudEvents wiring.

Re-exports the bus factory and the publish helper so handlers can do::

    from app.events import event_bus, publish

without reaching into the weld-events Protocol directly. Swap the
transport in :mod:`app.events.bus` if/when this service moves off
Postgres ``LISTEN/NOTIFY``.
"""

from __future__ import annotations

from app.events.bus import build_event_bus, publish

__all__ = ["build_event_bus", "publish"]

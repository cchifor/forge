"""Public types for the SSE streaming layer (vendored, weld-free).

These types are intentionally agnostic of the concrete CloudEvent class
the service ships — the streamer duck-types on :class:`CloudEventLike`
and :class:`EventBusLike` so the ``app.events`` package can stay vendored
without forcing a dependency direction either way.

Tenant / actor context is OPTIONAL on :class:`SubscriberCtx`: a
single-tenant service simply leaves it unset. This module imports only
the stdlib.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CloudEventLike(Protocol):
    """Duck-typed CloudEvent — what the streamer reads off each event."""

    id: str
    type: str
    data: dict[str, Any]


class EventBusLike(Protocol):
    """Duck-typed bus — the one method the streamer calls.

    Mirrors :class:`app.events.EventBus.subscribe`: the bus is bound to a
    single channel at construction, so ``subscribe`` takes no channel arg.
    """

    def subscribe(
        self, *, raise_on_backpressure_drop: bool = ...
    ) -> AsyncIterator[CloudEventLike]: ...


@dataclass(frozen=True, slots=True)
class SubscriberCtx:
    """Per-connection metadata passed through to filter + replay callables.

    ``last_event_id`` is the raw ``Last-Event-ID`` request header (the
    SSE reconnect handshake); ``None`` when the client connects fresh.
    ``tenant_id`` / ``user_id`` are OPTIONAL — set only by tenant-aware
    services. ``extra`` carries anything a specific filter needs.
    """

    last_event_id: str | None = None
    client_ip: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StreamFrame:
    """A wire-level SSE frame produced by a stream's :data:`Filter`.

    Filters return a :class:`StreamFrame` to deliver an event, or
    ``None`` to drop it. ``data`` is JSON-encoded by the streamer; the
    filter passes the structured dict. ``id`` populates SSE
    ``Last-Event-ID`` for replay; each stream picks its own id source.
    """

    data: dict[str, Any]
    event: str | None = None
    id: str | None = None


# An async callable that decides whether (and how) to deliver an event
# during the live phase. Returning ``None`` drops the event; returning a
# :class:`StreamFrame` yields it on the wire. Async because real-world
# filters may need DB lookups (per-user dismissal, ACL checks). The
# streamer invokes the filter exactly once per event.
Filter = Callable[["CloudEventLike", SubscriberCtx], Awaitable["StreamFrame | None"]]


# A per-stream callback that gap-fills events the client missed between
# disconnect and reconnect. Receives the parsed ``Last-Event-ID`` and the
# subscriber context, and yields each missed frame in order. Yields
# wire-ready :class:`StreamFrame` directly (replay is a ``WHERE id >
# cursor`` query — no live-phase filter applies).
ReplayProvider = Callable[[str | None, SubscriberCtx], AsyncIterator["StreamFrame"]]


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """Per-stream configuration.

    ``heartbeat_s`` is the keepalive cadence (sse-starlette owns the
    actual ping). ``queue_max`` bounds the per-connection buffer.
    ``max_stream_seconds`` caps a connection's lifetime so reverse
    proxies / replica rebalancing pick up cleanly. ``event_filter`` and
    ``replay_provider`` are optional hooks; the defaults deliver every
    event and do no replay.
    """

    heartbeat_s: float = 15.0
    queue_max: int = 1024
    max_stream_seconds: float = 3600.0
    stream_name: str = "stream"
    event_filter: Filter | None = None
    replay_provider: ReplayProvider | None = None

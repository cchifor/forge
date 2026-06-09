"""Event bus — :class:`EventBus` protocol + transports + factory (vendored).

The transport is pluggable behind :class:`EventBus`. Two implementations
ship here:

* :class:`PostgresNotifyBus` — Postgres ``LISTEN/NOTIFY`` on a single
  channel. A process-level multiplexer: one connection per replica fans
  ``NOTIFY`` payloads out to in-process subscribers via bounded
  ``asyncio.Queue`` instances, so the service doesn't open one Postgres
  backend per concurrent subscriber. Postgres-only.
* :class:`InMemoryEventBus` — same protocol, no database; subscribers in
  the same process. For tests and local dev.

A future migration to NATS / Redis Streams / Kafka is a single new
implementation behind the same Protocol — producers and subscribers do
not change.

The bus is bound to one channel at construction (``settings.events.channel``
by default). ``publish(event)`` and ``subscribe()`` both operate on that
channel, so call sites never pass channel names around.

This module imports only the stdlib + sqlalchemy (+ the sibling
``envelope`` / ``otel`` modules). No private SDKs.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol

from app.events.envelope import CloudEvent
from app.events.otel import (
    SYSTEM_IN_MEMORY,
    SYSTEM_POSTGRES_NOTIFY,
    inject_traceparent,
    publish_span,
    receive_span,
)
from sqlalchemy import text

if TYPE_CHECKING:
    from app.core.config.domain import Settings
    from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)

# Per-subscriber queue depth before the bus force-drops a slow consumer.
SUBSCRIBER_QUEUE_MAX = 256
HEARTBEAT_INTERVAL_SECONDS = 30.0
ATTACH_RETRY_BASE_SECONDS = 0.5
ATTACH_RETRY_MAX_SECONDS = 10.0

_NOTIFY_SQL = text("SELECT pg_notify(:c, :p)")


class BackpressureError(Exception):
    """Raised in a subscriber iterator when the bus force-closed it
    because its bounded queue overflowed (the consumer fell behind the
    producer rate).

    Opt-in via ``subscribe(..., raise_on_backpressure_drop=True)`` so
    callers that re-subscribe in a loop keep their silent-end semantics.
    Lets a streaming layer distinguish "slow consumer was dropped" from
    the other end-of-stream causes (bus shutdown, lifetime cap).
    """

    def __init__(self, channel: str) -> None:
        super().__init__(f"subscriber dropped due to backpressure on channel {channel!r}")
        self.channel = channel


class EventBus(Protocol):
    """Generic publish/subscribe interface.

    Implementations are free to choose any transport as long as they
    preserve: at-least-once delivery within a single replica's process
    while the subscriber is active (cross-process durability comes from
    the producer-side outbox, not the bus); prompt resource cleanup on
    subscriber cancellation; ``close()`` terminates every subscription.
    """

    channel: str

    async def start(self) -> None:
        """Bring the transport up. Idempotent."""
        ...

    async def stop(self) -> None:
        """Tear the transport down. Idempotent; alias of :meth:`close`."""
        ...

    async def publish(self, event: CloudEvent) -> None:
        """Publish ``event`` on the bus's channel."""
        ...

    def subscribe(
        self,
        *,
        raise_on_backpressure_drop: bool = False,
    ) -> AsyncIterator[CloudEvent]:
        """Stream :class:`CloudEvent`s on the bus's channel until canceled."""
        ...

    async def close(self) -> None:
        """Drop all subscribers and connections."""
        ...


class _Subscriber:
    __slots__ = ("closed", "dropped_due_to_backpressure", "queue")

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAX)
        self.closed = False
        self.dropped_due_to_backpressure = False


class InMemoryEventBus:
    """In-process :class:`EventBus` — no database. For tests and dev.

    ``publish`` serializes through :meth:`CloudEvent.to_json` (so size
    limits + envelope validation fire exactly as on the Postgres path)
    then fans the payload out to every live subscriber's bounded queue.
    """

    def __init__(self, channel: str = "domain_events") -> None:
        self.channel = channel
        self._subscribers: set[_Subscriber] = set()
        self._closed = False

    async def start(self) -> None:  # pragma: no cover - trivial
        self._closed = False

    async def stop(self) -> None:
        await self.close()

    async def publish(self, event: CloudEvent) -> None:
        if self._closed:
            raise RuntimeError("InMemoryEventBus is closed")
        instrumented = inject_traceparent(event)
        with publish_span(SYSTEM_IN_MEMORY, self.channel, instrumented):
            payload = instrumented.to_json()
            for sub in tuple(self._subscribers):
                if sub.closed:
                    continue
                try:
                    sub.queue.put_nowait(payload)
                except asyncio.QueueFull:
                    log.warning("InMemoryEventBus subscriber backpressure — dropping")
                    _drop_for_backpressure(sub)

    async def subscribe(
        self,
        *,
        raise_on_backpressure_drop: bool = False,
    ) -> AsyncIterator[CloudEvent]:
        if self._closed:
            raise RuntimeError("InMemoryEventBus is closed")
        sub = _Subscriber()
        self._subscribers.add(sub)
        try:
            async for event in _drain_subscriber(
                sub, self.channel, raise_on_backpressure_drop, SYSTEM_IN_MEMORY
            ):
                yield event
        finally:
            self._subscribers.discard(sub)

    async def close(self) -> None:
        self._closed = True
        for sub in self._subscribers:
            sub.closed = True
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover - queue full + close race
                pass
        self._subscribers.clear()


class PostgresNotifyBus:
    """Postgres ``LISTEN/NOTIFY`` :class:`EventBus`.

    Holds one asyncpg connection per replica (not per subscriber) and
    fans ``NOTIFY`` payloads out to in-process subscribers via bounded
    queues. SQLite has no ``LISTEN/NOTIFY``; this transport is
    Postgres-only.
    """

    def __init__(self, engine: AsyncEngine, channel: str = "domain_events") -> None:
        self._engine = engine
        self.channel = channel
        self._raw_conn = None
        self._asyncpg_conn = None
        self._conn_lock = asyncio.Lock()
        self._subscribers: set[_Subscriber] = set()
        self._listening = False
        self._closed = False
        self._supervisor: asyncio.Task | None = None

    async def start(self) -> None:
        """Eagerly open the listen connection so the first subscriber
        doesn't pay the connect latency. Idempotent."""
        self._closed = False
        async with self._conn_lock:
            await self._ensure_listener_locked()

    async def stop(self) -> None:
        await self.close()

    async def publish(self, event: CloudEvent) -> None:
        """Publish outside any caller transaction.

        Uses a short-lived connection from the engine pool — the NOTIFY
        fires at statement commit. For in-transaction emit (atomic with
        the caller's writes) the outbox + relay path is preferred; the
        relay calls this method.
        """
        if self._closed:
            raise RuntimeError("PostgresNotifyBus is closed")
        instrumented = inject_traceparent(event)
        with publish_span(SYSTEM_POSTGRES_NOTIFY, self.channel, instrumented):
            payload = instrumented.to_json()
            async with self._engine.begin() as conn:
                await conn.execute(_NOTIFY_SQL, {"c": self.channel, "p": payload})

    async def subscribe(
        self,
        *,
        raise_on_backpressure_drop: bool = False,
    ) -> AsyncIterator[CloudEvent]:
        if self._closed:
            raise RuntimeError("PostgresNotifyBus is closed")
        sub = _Subscriber()
        await self._attach(sub)
        try:
            async for event in _drain_subscriber(
                sub, self.channel, raise_on_backpressure_drop, SYSTEM_POSTGRES_NOTIFY
            ):
                yield event
        finally:
            self._detach(sub)

    async def close(self) -> None:
        self._closed = True
        if self._supervisor is not None:
            self._supervisor.cancel()
            try:
                await self._supervisor
            except (asyncio.CancelledError, Exception):  # pragma: no cover - teardown
                pass
            self._supervisor = None
        for sub in self._subscribers:
            sub.closed = True
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover - queue full + close race
                pass
        self._subscribers.clear()
        await self._close_connection()

    # ── Internals ──────────────────────────────────────────────────────

    async def _attach(self, sub: _Subscriber) -> None:
        first = len(self._subscribers) == 0
        self._subscribers.add(sub)
        if first:
            async with self._conn_lock:
                await self._ensure_listener_locked()

    def _detach(self, sub: _Subscriber) -> None:
        self._subscribers.discard(sub)

    async def _ensure_listener_locked(self) -> None:
        if self._listening and self._asyncpg_conn is not None:
            return
        delay = ATTACH_RETRY_BASE_SECONDS
        for attempt in range(5):
            await self._ensure_connection_locked()
            if self._asyncpg_conn is None:
                await asyncio.sleep(min(delay, ATTACH_RETRY_MAX_SECONDS))
                delay *= 2
                continue
            try:
                await self._asyncpg_conn.add_listener(self.channel, self._on_notify)
                self._listening = True
                self._ensure_supervisor()
                return
            except Exception as exc:
                log.warning(
                    "add_listener failed for %s (attempt %d): %s",
                    self.channel,
                    attempt + 1,
                    exc,
                )
                await self._close_connection_locked()
                await asyncio.sleep(min(delay, ATTACH_RETRY_MAX_SECONDS))
                delay *= 2

    async def _ensure_connection_locked(self) -> None:
        if self._asyncpg_conn is not None:
            return
        try:
            self._raw_conn = await self._engine.raw_connection()
            self._asyncpg_conn = self._raw_conn.driver_connection
        except Exception as exc:
            log.warning("EventBus connection acquire failed: %s", exc)
            self._raw_conn = None
            self._asyncpg_conn = None

    async def _close_connection_locked(self) -> None:
        if self._raw_conn is not None:
            try:
                self._raw_conn.close()
            except Exception:  # pragma: no cover - best-effort close
                pass
        self._raw_conn = None
        self._asyncpg_conn = None
        self._listening = False

    async def _close_connection(self) -> None:
        async with self._conn_lock:
            await self._close_connection_locked()

    def _on_notify(self, _conn, _pid, _channel: str, payload: str) -> None:
        """asyncpg listener callback — synchronous, on the event loop."""
        for sub in tuple(self._subscribers):
            if sub.closed:
                continue
            try:
                sub.queue.put_nowait(payload)
            except asyncio.QueueFull:
                log.warning("EventBus subscriber backpressure on %s — dropping", self.channel)
                _drop_for_backpressure(sub)

    # ── Heartbeat supervisor ────────────────────────────────────────────
    # asyncpg's LISTEN socket can drop silently (idle TCP reaped by a
    # middlebox, a Postgres failover); the bus would then go quiet with no
    # error. A periodic ``SELECT 1`` on the listen connection detects that and
    # re-establishes the listener so the bus self-heals instead of dying.

    def _ensure_supervisor(self) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            return
        self._supervisor = asyncio.create_task(self._run_supervisor())

    async def _run_supervisor(self) -> None:
        while not self._closed:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise
            if self._closed:
                return
            conn = self._asyncpg_conn
            if conn is None or not self._listening:
                continue
            try:
                # Cheapest liveness probe; round-trips the listen socket.
                await conn.fetchval("SELECT 1")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(
                    "EventBus heartbeat failed on %s (%s) — resuming subscribers and "
                    "resetting listen connection",
                    self.channel,
                    exc,
                )
                await self._broadcast_resume_and_reset()

    async def _broadcast_resume_and_reset(self) -> None:
        """Recover from a dropped LISTEN socket.

        Events published while the socket was down were missed — the bounded
        per-subscriber queues can't be trusted to have caught them. Poison the
        current subscribers so each SSE stream ends cleanly; the client's
        EventSource reconnects and the stream's replay phase (Last-Event-ID)
        backfills the gap. Then reset + re-establish the listener so new events
        flow again.
        """
        for sub in tuple(self._subscribers):
            sub.closed = True
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover - full queue + resume race
                pass
        self._subscribers.clear()
        async with self._conn_lock:
            await self._close_connection_locked()
            await self._ensure_listener_locked()


def _drop_for_backpressure(sub: _Subscriber) -> None:
    """Force-close a subscriber whose queue overflowed.

    Drops one queued event to make room so the consumer wakes on the
    poison ``None`` marker and terminates cleanly (with a
    :class:`BackpressureError` if it opted in).
    """
    sub.closed = True
    sub.dropped_due_to_backpressure = True
    try:
        sub.queue.get_nowait()
    except asyncio.QueueEmpty:  # pragma: no cover - queue already drained
        pass
    try:
        sub.queue.put_nowait(None)
    except asyncio.QueueFull:  # pragma: no cover - still full after a drain
        pass


async def _drain_subscriber(
    sub: _Subscriber,
    channel: str,
    raise_on_backpressure_drop: bool,
    system: str,
) -> AsyncIterator[CloudEvent]:
    """Yield parsed CloudEvents off a subscriber's queue until poisoned.

    Malformed payloads (e.g. a message from a non-CloudEvents producer
    on the same channel) are dropped with a warning rather than
    poisoning the stream.
    """
    while True:
        payload = await sub.queue.get()
        if payload is None:
            if raise_on_backpressure_drop and sub.dropped_due_to_backpressure:
                raise BackpressureError(channel)
            return
        try:
            event = CloudEvent.from_json(payload)
        except Exception as exc:
            log.warning("Dropping non-CloudEvent payload on %s: %s — %.200s", channel, exc, payload)
            continue
        with receive_span(system, channel, event):
            yield event


async def build_event_bus(settings: Settings, engine: AsyncEngine) -> EventBus:
    """Construct the configured :class:`EventBus` and start it.

    Reads ``settings.events.bus`` for the transport and
    ``settings.events.channel`` for the channel. ``postgres_notify`` is
    the default platform transport; ``memory`` is for tests and dev.
    """
    transport = settings.events.bus
    channel = settings.events.channel
    if transport == "postgres_notify":
        bus: EventBus = PostgresNotifyBus(engine=engine, channel=channel)
        await bus.start()
        return bus
    if transport == "memory":
        bus = InMemoryEventBus(channel=channel)
        await bus.start()
        return bus
    raise ValueError(f"Unsupported events.bus transport: {transport!r}")


async def publish(bus: EventBus, event: CloudEvent) -> None:
    """Thin wrapper so call sites don't import :class:`EventBus` directly."""
    await bus.publish(event)

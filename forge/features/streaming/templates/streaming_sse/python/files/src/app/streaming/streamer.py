"""CloudEventStreamer + factory — the SSE delivery primitive (vendored).

The streamer composes ``sse-starlette`` (transport: heartbeat,
disconnect detection, framing, retry preamble) with the service's own
concerns: bus subscription, ``Last-Event-ID`` replay, an optional pure
filter, a lifetime cap, and graceful backpressure handling. Per-service
endpoints become a five-line declaration; there is no timeout-driven
re-arm loop, so the SSE busy-loop bug class is precluded by construction
(the generator yields only on real events).

The streamer subscribes off the same :class:`app.events.EventBus`
instance the rest of the app publishes to — the bus is bound to one
channel, so the streamer doesn't pass channel names around.

This module imports only the stdlib + sse-starlette + starlette (+ the
sibling ``types`` module and the duck-typed bus). No private SDKs, and
no hard tenant requirement — tenant context on :class:`SubscriberCtx` is
optional.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from app.events.bus import BackpressureError
from app.streaming.types import (
    CloudEventLike,
    EventBusLike,
    StreamConfig,
    StreamFrame,
    SubscriberCtx,
)
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from starlette.requests import Request

if TYPE_CHECKING:
    from app.core.config.domain import Settings


def default_stream_config(settings: Settings) -> StreamConfig:
    return StreamConfig(
        heartbeat_s=settings.streaming.heartbeat_s,
        queue_max=settings.streaming.queue_max,
    )


class CloudEventStreamer:
    """Delivers bus-published CloudEvents to browser tabs over SSE.

    Construct once per service (typically registered in the DI container
    alongside the :class:`EventBus` provider). The instance is stateless
    across calls — each :meth:`stream` opens a fresh subscription.
    """

    def __init__(self, bus: EventBusLike, default_config: StreamConfig) -> None:
        self._bus = bus
        self._default_config = default_config

    def stream(
        self,
        request: Request,
        config: StreamConfig,
        ctx: SubscriberCtx,
    ) -> EventSourceResponse:
        """Return an SSE response that delivers events to ``ctx``."""
        return EventSourceResponse(
            self._iter_sse_events(request, config, ctx),
            ping=int(config.heartbeat_s),
        )

    # ── Internal generator (target of unit tests) ─────────────────────

    async def _iter_events(
        self,
        request: Request,
        config: StreamConfig,
        ctx: SubscriberCtx,
    ) -> AsyncIterator[StreamFrame]:
        """Yield :class:`StreamFrame` instances. Lifetime-capped.

        The loop awaits ``bus.subscribe()`` which blocks until an event
        arrives — there is no timeout-driven re-arm, so the generator
        cannot spin. Heartbeats are emitted by sse-starlette in the
        wrapping response, not here.
        """
        # ── Replay phase ──────────────────────────────────────────────
        if config.replay_provider is not None:
            async for frame in config.replay_provider(ctx.last_event_id, ctx):
                yield frame

        # ── Live phase, lifetime-capped ───────────────────────────────
        try:
            async with asyncio.timeout(config.max_stream_seconds):
                async for event in self._bus.subscribe(raise_on_backpressure_drop=True):
                    frame = await self._project(event, ctx, config)
                    if frame is not None:
                        yield frame
        except TimeoutError:
            # Lifetime cap reached — graceful end. Reverse proxies /
            # replica rebalancing pick up from here.
            return
        except BackpressureError:
            # The bus force-closed this subscriber because its bounded
            # queue overflowed (a slow consumer). End the SSE response
            # gracefully — sse-starlette closes it, the FE's EventSource
            # auto-reconnects, and the replay phase fills the gap if a
            # replay provider is configured.
            return

    async def _project(
        self,
        event: CloudEventLike,
        ctx: SubscriberCtx,
        config: StreamConfig,
    ) -> StreamFrame | None:
        """Apply the configured filter, or default to delivering the
        event verbatim (CloudEvent ``type`` as the SSE event name,
        ``id`` as the Last-Event-ID cursor)."""
        if config.event_filter is not None:
            return await config.event_filter(event, ctx)
        return StreamFrame(data=event.data, event=event.type, id=event.id)

    async def _iter_sse_events(
        self,
        request: Request,
        config: StreamConfig,
        ctx: SubscriberCtx,
    ) -> AsyncIterator[ServerSentEvent]:
        """Bridge :meth:`_iter_events` (StreamFrame) to sse-starlette's
        :class:`ServerSentEvent` shape."""
        async for frame in self._iter_events(request, config, ctx):
            yield ServerSentEvent(
                data=json.dumps(frame.data, default=str),
                event=frame.event,
                id=frame.id,
            )


def build_streamer(bus: EventBusLike, settings: Settings) -> CloudEventStreamer:
    return CloudEventStreamer(bus=bus, default_config=default_stream_config(settings))

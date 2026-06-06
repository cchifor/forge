"""Fragment unit tests for the vendored SSE streamer (weld-free).

Runs inside the generated project — imports ``app.streaming.*`` and
``app.events.*`` only, never ``weld``. Drives the streamer's internal
``_iter_events`` generator (the SSE transport layer is sse-starlette's
job) to cover: default projection of CloudEvents to frames, the
``Last-Event-ID`` replay phase, the optional filter, and graceful end on
a backpressure drop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.events import CloudEvent, InMemoryEventBus
from app.events.bus import BackpressureError
from app.streaming import CloudEventStreamer, StreamConfig, StreamFrame, SubscriberCtx


class _FakeRequest:
    """Minimal stand-in — the vendored generator only needs an object."""


async def _collect(gen: AsyncIterator[StreamFrame], n: int) -> list[StreamFrame]:
    out: list[StreamFrame] = []
    async for frame in gen:
        out.append(frame)
        if len(out) >= n:
            break
    return out


async def test_default_projection_maps_event_to_frame() -> None:
    bus = InMemoryEventBus()
    await bus.start()
    streamer = CloudEventStreamer(bus=bus, default_config=StreamConfig())
    cfg = StreamConfig()
    ctx = SubscriberCtx()

    task = asyncio.create_task(_collect(streamer._iter_events(_FakeRequest(), cfg, ctx), 1))
    await asyncio.sleep(0)
    await bus.publish(CloudEvent(source="svc", type="ping", id="evt-1", data={"x": 1}))
    frames = await asyncio.wait_for(task, timeout=2.0)

    assert frames[0].event == "ping"
    assert frames[0].id == "evt-1"
    assert frames[0].data == {"x": 1}
    await bus.close()


async def test_replay_phase_runs_before_live() -> None:
    bus = InMemoryEventBus()
    await bus.start()

    async def replay(last_id, ctx) -> AsyncIterator[StreamFrame]:
        assert last_id == "cursor-42"
        yield StreamFrame(data={"replayed": True}, event="old", id="r1")

    cfg = StreamConfig(replay_provider=replay)
    streamer = CloudEventStreamer(bus=bus, default_config=StreamConfig())
    ctx = SubscriberCtx(last_event_id="cursor-42")

    task = asyncio.create_task(_collect(streamer._iter_events(_FakeRequest(), cfg, ctx), 2))
    await asyncio.sleep(0)
    await bus.publish(CloudEvent(source="svc", type="live", id="evt-9"))
    frames = await asyncio.wait_for(task, timeout=2.0)

    assert frames[0].event == "old"
    assert frames[0].data == {"replayed": True}
    assert frames[1].event == "live"
    await bus.close()


async def test_filter_can_drop_events() -> None:
    bus = InMemoryEventBus()
    await bus.start()

    async def only_orders(event, ctx) -> StreamFrame | None:
        if not event.type.startswith("order."):
            return None
        return StreamFrame(data=event.data, event=event.type, id=event.id)

    cfg = StreamConfig(event_filter=only_orders)
    streamer = CloudEventStreamer(bus=bus, default_config=StreamConfig())

    gen = streamer._iter_events(_FakeRequest(), cfg, SubscriberCtx())
    task = asyncio.create_task(_collect(gen, 1))
    await asyncio.sleep(0)
    await bus.publish(CloudEvent(source="svc", type="user.created", id="u1"))  # dropped
    await bus.publish(CloudEvent(source="svc", type="order.placed", id="o1"))  # kept
    frames = await asyncio.wait_for(task, timeout=2.0)

    assert len(frames) == 1
    assert frames[0].event == "order.placed"
    await bus.close()


async def test_backpressure_ends_stream_gracefully() -> None:
    """A BackpressureError from the bus ends the generator, not crashes."""

    class _DropBus:
        async def subscribe(self, *, raise_on_backpressure_drop: bool = False):
            raise BackpressureError("domain_events")
            yield  # pragma: no cover - unreachable, makes this an async gen

    streamer = CloudEventStreamer(bus=_DropBus(), default_config=StreamConfig())
    gen = streamer._iter_events(_FakeRequest(), StreamConfig(), SubscriberCtx())
    frames = [f async for f in gen]
    assert frames == []


async def test_lifetime_cap_ends_stream() -> None:
    bus = InMemoryEventBus()
    await bus.start()
    cfg = StreamConfig(max_stream_seconds=0.05)
    streamer = CloudEventStreamer(bus=bus, default_config=StreamConfig())
    frames = [f async for f in streamer._iter_events(_FakeRequest(), cfg, SubscriberCtx())]
    assert frames == []
    await bus.close()


def test_default_stream_config_reads_settings() -> None:
    from app.streaming import default_stream_config

    class _Streaming:
        heartbeat_s = 7.0
        queue_max = 99

    class _Settings:
        streaming = _Streaming()

    cfg = default_stream_config(_Settings())
    assert cfg.heartbeat_s == 7.0
    assert cfg.queue_max == 99


def test_streamconfig_defaults() -> None:
    cfg = StreamConfig()
    assert cfg.heartbeat_s == 15.0
    assert cfg.queue_max == 1024
    assert cfg.replay_provider is None
    assert cfg.event_filter is None

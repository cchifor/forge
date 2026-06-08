"""Fragment unit tests for the vendored CloudEvents bus (weld-free).

Runs inside the generated project — imports ``app.events.*`` only, never
``weld``. Covers: optional tenant/actor on the envelope, JSON
round-trip + size cap, and InMemoryEventBus publish/subscribe fanout +
backpressure semantics.
"""

from __future__ import annotations

import asyncio

import pytest
from app.events import CloudEvent, InMemoryEventBus
from app.events.bus import SUBSCRIBER_QUEUE_MAX, BackpressureError


def test_cloudevent_tenant_and_actor_optional() -> None:
    ev = CloudEvent(source="svc", type="thing.happened")
    assert ev.tenantid is None
    assert ev.actorid is None
    # Round-trips through JSON without the optional extensions.
    again = CloudEvent.from_json(ev.to_json())
    assert again.tenantid is None
    assert again.type == "thing.happened"


def test_cloudevent_carries_tenant_when_set() -> None:
    ev = CloudEvent(source="svc", type="t", tenantid="tenant-1", actorid="actor-9")
    again = CloudEvent.from_json(ev.to_json())
    assert again.tenantid == "tenant-1"
    assert again.actorid == "actor-9"


def test_cloudevent_rejects_oversized_payload() -> None:
    big = CloudEvent(source="svc", type="t", data={"blob": "x" * 8000})
    with pytest.raises(ValueError, match="exceeds"):
        big.to_json()


def test_cloudevent_rejects_unknown_specversion() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CloudEvent(source="svc", type="t", specversion="0.3")


async def test_in_memory_bus_publish_subscribe() -> None:
    bus = InMemoryEventBus(channel="domain_events")
    await bus.start()
    received: list[CloudEvent] = []

    async def consume() -> None:
        async for ev in bus.subscribe():
            received.append(ev)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the subscriber attach
    await bus.publish(CloudEvent(source="svc", type="a"))
    await bus.publish(CloudEvent(source="svc", type="b"))
    await asyncio.wait_for(task, timeout=2.0)

    assert [e.type for e in received] == ["a", "b"]
    await bus.close()


async def test_in_memory_bus_fanout_to_multiple_subscribers() -> None:
    bus = InMemoryEventBus()
    await bus.start()
    got_a: list[str] = []
    got_b: list[str] = []

    async def consume(sink: list[str]) -> None:
        async for ev in bus.subscribe():
            sink.append(ev.type)
            return

    ta = asyncio.create_task(consume(got_a))
    tb = asyncio.create_task(consume(got_b))
    await asyncio.sleep(0)
    await bus.publish(CloudEvent(source="svc", type="broadcast"))
    await asyncio.wait_for(asyncio.gather(ta, tb), timeout=2.0)
    assert got_a == ["broadcast"]
    assert got_b == ["broadcast"]
    await bus.close()


async def test_in_memory_bus_backpressure_drops_slow_consumer() -> None:
    bus = InMemoryEventBus()
    await bus.start()
    drained: list[CloudEvent] = []

    async def slow() -> None:
        # Subscribe but never pull, so the queue overflows.
        async for ev in bus.subscribe(raise_on_backpressure_drop=True):
            drained.append(ev)

    task = asyncio.create_task(slow())
    await asyncio.sleep(0)
    # Overflow the bounded queue.
    for i in range(SUBSCRIBER_QUEUE_MAX + 10):
        await bus.publish(CloudEvent(source="svc", type=f"e{i}"))
    with pytest.raises(BackpressureError):
        await asyncio.wait_for(task, timeout=2.0)
    await bus.close()


async def test_subscribe_drops_non_cloudevent_payload() -> None:
    """A non-CloudEvent string on the channel is skipped, not fatal."""
    bus = InMemoryEventBus()
    await bus.start()
    received: list[str] = []

    async def consume() -> None:
        async for ev in bus.subscribe():
            received.append(ev.type)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    # Inject a junk payload directly onto the live subscriber's queue,
    # then a valid event. The junk is dropped with a warning.
    sub = next(iter(bus._subscribers))  # type: ignore[attr-defined]
    sub.queue.put_nowait("not json at all")
    await bus.publish(CloudEvent(source="svc", type="valid"))
    await asyncio.wait_for(task, timeout=2.0)
    assert received == ["valid"]
    await bus.close()

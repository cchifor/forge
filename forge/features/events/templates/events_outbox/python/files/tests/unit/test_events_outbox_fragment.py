"""Fragment unit tests for the vendored transactional outbox (weld-free).

Runs inside the generated project against an in-memory SQLite engine —
imports ``app.events.*`` only, never ``weld``. Covers: OutboxStore
insert (with and without the optional partition/actor keys), the relay
drain round-tripping rows back into CloudEvents, and published rows being
marked so they aren't re-emitted.
"""

from __future__ import annotations

import pytest
from app.events import CloudEvent, InMemoryEventBus
from app.events.outbox import (
    OUTBOX_METADATA,
    OUTBOX_TABLE,
    OutboxRelay,
    OutboxStore,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(OUTBOX_METADATA.create_all)
    yield eng
    await eng.dispose()


async def test_store_insert_single_tenant_leaves_keys_null(engine) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        store = OutboxStore(session=session)
        await store.insert(CloudEvent(source="svc", type="thing.happened"))
        await session.commit()
    async with sm() as session:
        rows = list(await session.execute(OUTBOX_TABLE.select()))
    assert len(rows) == 1
    assert rows[0].partition_key is None
    assert rows[0].actor_key is None
    assert rows[0].event_type == "thing.happened"


async def test_store_insert_maps_tenant_and_actor(engine) -> None:
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        store = OutboxStore(session=session)
        await store.insert(
            CloudEvent(source="svc", type="t", tenantid="tenant-7", actorid="actor-3")
        )
        await session.commit()
    async with sm() as session:
        row = (await session.execute(OUTBOX_TABLE.select())).one()
    assert row.partition_key == "tenant-7"
    assert row.actor_key == "actor-3"


async def test_relay_drains_and_publishes(engine) -> None:
    bus = InMemoryEventBus()
    await bus.start()
    delivered: list[CloudEvent] = []

    import asyncio

    async def consume() -> None:
        async for ev in bus.subscribe():
            delivered.append(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as session:
        await OutboxStore(session=session).insert(
            CloudEvent(source="svc", type="order.created", tenantid="t1", data={"k": "v"})
        )
        await session.commit()

    relay = OutboxRelay(engine=engine, bus=bus, poll_interval_s=0.01)
    published = await relay.drain_once()
    assert published == 1
    await asyncio.wait_for(task, timeout=2.0)

    assert delivered[0].type == "order.created"
    assert delivered[0].tenantid == "t1"
    assert delivered[0].data == {"k": "v"}

    # A second drain finds nothing — the row is marked published.
    assert await relay.drain_once() == 0
    await bus.close()

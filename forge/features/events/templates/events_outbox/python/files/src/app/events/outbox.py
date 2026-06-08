"""Transactional outbox for the event bus (vendored, weld-free).

Producers append rows to ``outbox`` in the *same transaction* as their
domain writes — no dual-write race, no lost events on subscriber
downtime. The :class:`OutboxRelay` polls the table and publishes via the
:class:`EventBus`, marking each row ``published_at`` after a successful
publish. On failure, ``attempt_count`` / ``next_attempt_at`` are bumped
with exponential backoff; rows past :data:`MAX_PUBLISH_ATTEMPTS` are left
for human review.

Multiple replicas of the same service can run the relay concurrently on
Postgres: ``SELECT ... FOR UPDATE SKIP LOCKED`` claims each row for
exactly one replica per cycle. On SQLite (single-writer) the clause is
omitted.

The optional CloudEvent extensions map to generic, NULLABLE columns:
``partition_key`` (from ``tenantid``) and ``actor_key`` (from
``actorid``). A single-tenant service simply leaves them NULL — there is
no hard tenant requirement. Stored as strings so non-UUID keys are
accepted; the relay round-trips them back onto the rebuilt CloudEvent.

This module imports only the stdlib + sqlalchemy (+ the sibling
``envelope`` / ``bus`` modules). No private SDKs.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from app.events.bus import EventBus
from app.events.envelope import CloudEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)

RELAY_BATCH_SIZE = 100
MAX_PUBLISH_ATTEMPTS = 10

# Dedicated MetaData so the outbox table can travel without dragging an
# ORM ``Base``. The schema mirrors the Alembic migration shipped by this
# fragment exactly so the relay can poll without per-service mapping.
OUTBOX_METADATA = sa.MetaData()

OUTBOX_TABLE = sa.Table(
    "outbox",
    OUTBOX_METADATA,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column("event_type", sa.String(255), nullable=False),
    sa.Column("source", sa.String(255), nullable=False),
    sa.Column("subject", sa.String(255), nullable=True),
    # Generic, nullable partition / actor keys (formerly Strive's
    # tenant_id / actor_id). Single-tenant services leave them NULL.
    sa.Column("partition_key", sa.String(255), nullable=True),
    sa.Column("actor_key", sa.String(255), nullable=True),
    sa.Column("data", sa.JSON, nullable=False),
    sa.Column("traceparent", sa.String(255), nullable=True),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "attempt_count",
        sa.SmallInteger,
        nullable=False,
        server_default=sa.text("0"),
    ),
    sa.Column(
        "next_attempt_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("last_error", sa.Text, nullable=True),
    sa.Index(
        "ix_outbox_unpublished",
        "next_attempt_at",
        postgresql_where=sa.text("published_at IS NULL"),
    ),
)


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff capped at 5 minutes."""
    return min(2.0**attempt, 300.0)


def _row_to_event(row: sa.Row) -> CloudEvent:
    """Reconstruct a CloudEvent from an outbox row."""
    return CloudEvent(
        id=str(row.id),
        type=row.event_type,
        source=row.source,
        subject=row.subject,
        tenantid=row.partition_key,
        actorid=row.actor_key,
        data=row.data,
        time=row.created_at,
        traceparent=row.traceparent,
    )


class OutboxStore:
    """Append CloudEvents to the outbox within the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, event: CloudEvent) -> None:
        # Validate envelope size at the source — fail fast in the
        # producer's tx rather than blowing up the relay later.
        event.to_json()
        try:
            event_id = uuid.UUID(event.id)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"CloudEvent id must be a UUID string for the outbox, got {event.id!r}"
            ) from exc
        await self._session.execute(
            sa.insert(OUTBOX_TABLE).values(
                id=event_id,
                event_type=event.type,
                source=event.source,
                subject=event.subject,
                partition_key=event.tenantid,
                actor_key=event.actorid,
                data=event.data,
                traceparent=event.traceparent,
                created_at=event.time,
                next_attempt_at=event.time,
            )
        )


class OutboxRelay:
    """Background pump from the outbox table to the event bus."""

    def __init__(self, engine: AsyncEngine, bus: EventBus, poll_interval_s: float = 1.0) -> None:
        self._engine = engine
        self._bus = bus
        self._poll_interval_s = poll_interval_s
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="outbox-relay")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def drain_once(self) -> int:
        """Process one batch synchronously. Returns the number published.

        Useful for tests and for a lifespan-shutdown grace period.
        """
        return await self._publish_batch()

    async def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                published = await self._publish_batch()
                if published == 0:
                    await self._sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                log.exception("OutboxRelay batch failed: %s", exc)
                await self._sleep(self._poll_interval_s)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except TimeoutError:
            return

    async def _publish_batch(self) -> int:
        async with self._session_factory() as session:
            rows = await self._claim_batch(session)
            if not rows:
                return 0
            published_ids: list[Any] = []
            for row in rows:
                if await self._try_publish(session, row):
                    published_ids.append(row.id)
            if published_ids:
                await session.execute(
                    sa.update(OUTBOX_TABLE)
                    .where(OUTBOX_TABLE.c.id.in_(published_ids))
                    .values(published_at=_now())
                )
            await session.commit()
            return len(published_ids)

    async def _claim_batch(self, session: AsyncSession) -> list[sa.Row]:
        dialect = session.bind.dialect.name if session.bind else ""
        stmt: Any = (
            sa.select(OUTBOX_TABLE)
            .where(OUTBOX_TABLE.c.published_at.is_(None))
            .where(OUTBOX_TABLE.c.next_attempt_at <= _now())
            .order_by(OUTBOX_TABLE.c.created_at)
            .limit(RELAY_BATCH_SIZE)
        )
        # SKIP LOCKED lets multiple relay replicas drain the same outbox
        # without stepping on each other. SQLite lacks row locking.
        if dialect == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        result = await session.execute(stmt)
        return list(result)

    async def _try_publish(self, session: AsyncSession, row: sa.Row) -> bool:
        try:
            event = _row_to_event(row)
        except Exception as exc:
            log.exception("Outbox row %s is malformed: %s", row.id, exc)
            await self._mark_failed(session, row, str(exc))
            return False
        try:
            await self._bus.publish(event)
            return True
        except Exception as exc:
            log.warning(
                "OutboxRelay publish failed for %s (attempt %d/%d): %s",
                row.id,
                row.attempt_count + 1,
                MAX_PUBLISH_ATTEMPTS,
                exc,
            )
            await self._mark_failed(session, row, str(exc))
            return False

    async def _mark_failed(self, session: AsyncSession, row: sa.Row, reason: str) -> None:
        new_attempt = row.attempt_count + 1
        if new_attempt >= MAX_PUBLISH_ATTEMPTS:
            log.error(
                "Outbox row %s exhausted retries (%d) — left for human review",
                row.id,
                MAX_PUBLISH_ATTEMPTS,
            )
            await session.execute(
                sa.update(OUTBOX_TABLE)
                .where(OUTBOX_TABLE.c.id == row.id)
                .values(attempt_count=new_attempt, last_error=reason[:1000])
            )
            return
        await session.execute(
            sa.update(OUTBOX_TABLE)
            .where(OUTBOX_TABLE.c.id == row.id)
            .values(
                attempt_count=new_attempt,
                next_attempt_at=_now() + _dt.timedelta(seconds=_backoff_delay(new_attempt)),
                last_error=reason[:1000],
            )
        )


def build_outbox_store(session: AsyncSession) -> OutboxStore:
    return OutboxStore(session=session)


def build_outbox_relay(engine: AsyncEngine, bus: EventBus, poll_interval_s: float) -> OutboxRelay:
    return OutboxRelay(engine=engine, bus=bus, poll_interval_s=poll_interval_s)

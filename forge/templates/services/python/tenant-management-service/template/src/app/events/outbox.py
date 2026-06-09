"""Outbox relay — polls the outbox table and publishes to Valkey Streams.

Runs as a background asyncio task.  Each unpublished row is sent to the
Valkey Stream named by ``outbox.stream``, then marked as published.
Delivery is at-least-once: a consumer crash after XADD but before the
UPDATE will re-send on next poll.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class OutboxRelay:
    """Background poller that relays outbox rows to Valkey Streams."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_url: str,
        poll_interval: float = 2.0,
        batch_size: int = 100,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_async.from_url(redis_url, decode_responses=True)
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll_loop(), name="outbox-relay")
        logger.info("Outbox relay started (interval=%.1fs)", self._poll_interval)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._redis.aclose()
        logger.info("Outbox relay stopped.")

    async def _poll_loop(self) -> None:
        while True:
            try:
                count = await self._relay_batch()
                if count > 0:
                    logger.info("Outbox relay: published %d events", count)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Outbox relay error")
            await asyncio.sleep(self._poll_interval)

    async def _relay_batch(self) -> int:
        async with self._session_factory() as session:
            # Fetch unpublished rows
            result = await session.execute(
                text(
                    "SELECT id, event_id, event_type, stream, payload "
                    "FROM outbox WHERE published = FALSE "
                    "ORDER BY id LIMIT :limit"
                ),
                {"limit": self._batch_size},
            )
            rows = result.fetchall()

            if not rows:
                return 0

            for row in rows:
                row_id, event_id, event_type, stream, payload = row

                # XADD to Valkey Stream
                await self._redis.xadd(
                    stream,
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "payload": payload,
                    },
                )

                # Mark as published
                await session.execute(
                    text("UPDATE outbox SET published = TRUE WHERE id = :id"),
                    {"id": row_id},
                )

            await session.commit()
            return len(rows)

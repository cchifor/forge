"""Redis queue adapter — Redis lists with RPOPLPUSH for ack-safe delivery.

Simple adapter for small-to-medium workloads. For higher throughput +
scheduling, swap in the Hatchet / Temporal / SQS adapter via env config.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis

from app.ports.queue import QueueMessage, QueuePort


class RedisQueueAdapter(QueuePort):
    def __init__(self, url: str) -> None:
        self._client = redis.from_url(url, decode_responses=True)

    @staticmethod
    def _key(topic: str) -> str:
        return f"queue:{topic}"

    @staticmethod
    def _processing_key(topic: str) -> str:
        return f"queue:{topic}:processing"

    async def enqueue(
        self,
        *,
        topic: str,
        body: dict[str, Any],
        delay_seconds: int = 0,
    ) -> str:
        message_id = str(uuid.uuid4())
        envelope = json.dumps({"id": message_id, "body": body})
        if delay_seconds > 0:
            # Lightweight delayed-delivery: schedule a zadd into a sorted
            # set that the consumer polls. Real delayed queues (SQS/
            # Hatchet) belong in their own adapters.
            await self._client.zadd(
                f"{self._key(topic)}:delayed",
                {envelope: (await _now_ms()) + delay_seconds * 1000},
            )
        else:
            await self._client.lpush(self._key(topic), envelope)
        return message_id

    async def consume(
        self,
        *,
        topic: str,
        batch_size: int = 1,
    ) -> AsyncIterator[QueueMessage]:
        while True:
            raw = await self._client.rpoplpush(self._key(topic), self._processing_key(topic))
            if not raw:
                await asyncio.sleep(0.5)
                continue
            envelope = json.loads(raw)
            yield QueueMessage(id=envelope["id"], body=envelope["body"], receipt=raw)

    async def ack(self, *, topic: str, receipt: str) -> None:
        await self._client.lrem(self._processing_key(topic), 1, receipt)

    async def nack(self, *, topic: str, receipt: str, requeue: bool = True) -> None:
        await self._client.lrem(self._processing_key(topic), 1, receipt)
        if requeue:
            await self._client.lpush(self._key(topic), receipt)


async def _now_ms() -> int:
    import time

    return int(time.time() * 1000)

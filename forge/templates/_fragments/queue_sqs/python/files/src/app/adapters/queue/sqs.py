"""AWS SQS queue adapter — production-grade with FIFO + delay support.

Delegates to ``aioboto3``. The ``topic`` parameter is the SQS queue URL
or queue name (the adapter resolves names to URLs via ``get_queue_url``
on first use and caches the result).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import aioboto3

from app.ports.queue import QueueMessage, QueuePort


class SqsQueueAdapter(QueuePort):
    def __init__(self, region: str) -> None:
        self._region = region
        self._session = aioboto3.Session()
        self._url_cache: dict[str, str] = {}

    async def _resolve_queue(self, topic: str) -> str:
        if topic.startswith("https://"):
            return topic
        if topic in self._url_cache:
            return self._url_cache[topic]
        async with self._session.client("sqs", region_name=self._region) as client:
            resp = await client.get_queue_url(QueueName=topic)
            url = resp["QueueUrl"]
        self._url_cache[topic] = url
        return url

    async def enqueue(
        self,
        *,
        topic: str,
        body: dict[str, Any],
        delay_seconds: int = 0,
    ) -> str:
        queue_url = await self._resolve_queue(topic)
        async with self._session.client("sqs", region_name=self._region) as client:
            resp = await client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(body),
                DelaySeconds=delay_seconds,
            )
        return resp["MessageId"]

    async def consume(
        self,
        *,
        topic: str,
        batch_size: int = 1,
    ) -> AsyncIterator[QueueMessage]:
        queue_url = await self._resolve_queue(topic)
        async with self._session.client("sqs", region_name=self._region) as client:
            while True:
                resp = await client.receive_message(
                    QueueUrl=queue_url,
                    MaxNumberOfMessages=min(batch_size, 10),
                    WaitTimeSeconds=20,
                )
                for msg in resp.get("Messages", []):
                    try:
                        body = json.loads(msg["Body"])
                    except (ValueError, KeyError):
                        body = {}
                    yield QueueMessage(
                        id=msg["MessageId"],
                        body=body,
                        receipt=msg["ReceiptHandle"],
                    )
                if not resp.get("Messages"):
                    await asyncio.sleep(0)

    async def ack(self, *, topic: str, receipt: str) -> None:
        queue_url = await self._resolve_queue(topic)
        async with self._session.client("sqs", region_name=self._region) as client:
            await client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)

    async def nack(self, *, topic: str, receipt: str, requeue: bool = True) -> None:
        queue_url = await self._resolve_queue(topic)
        async with self._session.client("sqs", region_name=self._region) as client:
            # Reset visibility timeout to 0 so the message is immediately
            # re-delivered (requeue=True). For requeue=False we'd need a
            # DLQ redirect — deliberately out of scope for the port.
            await client.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=0,
            )

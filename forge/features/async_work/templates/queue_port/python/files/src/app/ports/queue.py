"""Queue port — capability contract for outbound work enqueuing + consumption.

Adapters live under ``app/adapters/queue/<provider>.py``. The port's
surface covers the 80% case: submit a task, consume a batch, ack on
success, nack + retry on failure. Advanced patterns (priority queues,
delayed delivery) are provider-specific and stay inside adapters.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class QueueMessage:
    """One message as delivered by a consumer."""

    id: str
    body: dict[str, Any]
    receipt: str  # opaque handle for ack/nack — provider-specific


class QueuePort(Protocol):
    async def enqueue(
        self,
        *,
        topic: str,
        body: dict[str, Any],
        delay_seconds: int = 0,
    ) -> str:
        """Enqueue one message; return the provider's message id."""

    async def consume(
        self,
        *,
        topic: str,
        batch_size: int = 1,
    ) -> AsyncIterator[QueueMessage]:
        """Yield messages from the named topic. Consumer acks via ``ack``."""

    async def ack(self, *, topic: str, receipt: str) -> None:
        """Acknowledge a message — removes it from the queue."""

    async def nack(self, *, topic: str, receipt: str, requeue: bool = True) -> None:
        """Reject a message — requeue by default for retry."""

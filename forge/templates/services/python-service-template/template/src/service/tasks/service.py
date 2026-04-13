"""Task service for enqueuing and querying background tasks."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service.tasks.models import BackgroundTask, TaskStatus

logger = logging.getLogger(__name__)


class TaskService:
    """Enqueue and query background tasks.

    Uses its own session factory (not the UoW) because task writes
    must commit independently of the caller's transaction.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def enqueue(
        self,
        task_type: str,
        *,
        payload: dict[str, Any] | None = None,
        max_retries: int = 3,
        scheduled_at: dt.datetime | None = None,
    ) -> UUID:
        """Create a new pending task and return its ID."""
        task = BackgroundTask(
            task_type=task_type,
            payload=payload or {},
            max_retries=max_retries,
            status=TaskStatus.PENDING,
        )
        if scheduled_at:
            task.scheduled_at = scheduled_at

        async with self._session_factory() as session:
            session.add(task)
            await session.commit()
            await session.refresh(task)
            logger.info("Enqueued task %s (type=%s)", task.id, task_type)
            return task.id

    async def get(self, task_id: UUID) -> BackgroundTask | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BackgroundTask).where(BackgroundTask.id == task_id)
            )
            return result.scalar_one_or_none()

    async def cancel(self, task_id: UUID) -> bool:
        """Cancel a pending task. Returns True if cancelled."""
        async with self._session_factory() as session:
            result = await session.execute(
                update(BackgroundTask)
                .where(
                    BackgroundTask.id == task_id,
                    BackgroundTask.status == TaskStatus.PENDING,
                )
                .values(status=TaskStatus.CANCELLED)
            )
            await session.commit()
            return result.rowcount > 0  # type: ignore[return-value]

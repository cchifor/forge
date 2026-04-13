"""Background task runner.

Polls the ``background_tasks`` table for PENDING tasks, claims them,
and dispatches to registered handlers. Supports retry with backoff
and graceful shutdown.

Usage in lifecycle::

    runner = BackgroundTaskRunner(session_factory, poll_interval=5.0)
    await runner.start()
    ...
    await runner.stop()  # drains in-flight tasks
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import traceback

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service.tasks.models import BackgroundTask, TaskStatus
from service.tasks.registry import get_handler

logger = logging.getLogger(__name__)


class BackgroundTaskRunner:
    """Polls the task queue and executes handlers."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval: float = 5.0,
        batch_size: int = 10,
        max_concurrent: int = 5,
    ):
        self._session_factory = session_factory
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._in_flight: set[asyncio.Task] = set()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(), name="task-runner")
        logger.info("Background task runner started (interval=%.1fs)", self._poll_interval)

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        # Drain in-flight tasks
        if self._in_flight:
            logger.info("Draining %d in-flight tasks...", len(self._in_flight))
            await asyncio.gather(*self._in_flight, return_exceptions=True)
        logger.info("Background task runner stopped.")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                tasks = await self._claim_tasks()
                for task in tasks:
                    await self._semaphore.acquire()
                    t = asyncio.create_task(self._execute_task(task))
                    self._in_flight.add(t)
                    t.add_done_callback(self._task_done)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in task poll loop")

            await asyncio.sleep(self._poll_interval)

    async def _claim_tasks(self) -> list[BackgroundTask]:
        """Atomically claim a batch of PENDING tasks."""
        now = func.now()
        async with self._session_factory() as session:
            result = await session.execute(
                select(BackgroundTask)
                .where(
                    BackgroundTask.status == TaskStatus.PENDING,
                    BackgroundTask.scheduled_at <= now,
                )
                .order_by(BackgroundTask.scheduled_at)
                .limit(self._batch_size)
                .with_for_update(skip_locked=True)
            )
            tasks = list(result.scalars().all())

            if not tasks:
                return []

            task_ids = [t.id for t in tasks]
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id.in_(task_ids))
                .values(
                    status=TaskStatus.RUNNING,
                    started_at=func.now(),
                    attempts=BackgroundTask.attempts + 1,
                )
            )
            await session.commit()

            # Refresh to get updated state
            for task in tasks:
                await session.refresh(task)

            logger.debug("Claimed %d tasks", len(tasks))
            return tasks

    async def _execute_task(self, task: BackgroundTask) -> None:
        handler = get_handler(task.task_type)
        if not handler:
            logger.error("No handler for task_type=%s (id=%s)", task.task_type, task.id)
            await self._mark_failed(task, f"No handler registered for '{task.task_type}'")
            return

        try:
            result = await handler(task.payload or {})
            await self._mark_completed(task, result)
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            if task.attempts < task.max_retries:
                await self._mark_retry(task, error_msg)
            else:
                await self._mark_failed(task, error_msg)

    async def _mark_completed(self, task: BackgroundTask, result: dict | None) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task.id)
                .values(
                    status=TaskStatus.COMPLETED,
                    result=result,
                    completed_at=func.now(),
                )
            )
            await session.commit()
        logger.info("Task %s completed (type=%s)", task.id, task.task_type)

    async def _mark_failed(self, task: BackgroundTask, error: str) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task.id)
                .values(
                    status=TaskStatus.FAILED,
                    error=error,
                    completed_at=func.now(),
                )
            )
            await session.commit()
        logger.error("Task %s failed (type=%s): %s", task.id, task.task_type, error[:200])

    async def _mark_retry(self, task: BackgroundTask, error: str) -> None:
        """Return task to PENDING with exponential backoff."""
        backoff = min(30 * (2 ** (task.attempts - 1)), 600)  # max 10min
        next_run = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=backoff)

        async with self._session_factory() as session:
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task.id)
                .values(
                    status=TaskStatus.PENDING,
                    error=error,
                    scheduled_at=next_run,
                )
            )
            await session.commit()
        logger.warning(
            "Task %s will retry in %ds (attempt %d/%d)",
            task.id,
            backoff,
            task.attempts,
            task.max_retries,
        )

    def _task_done(self, task: asyncio.Task) -> None:
        self._in_flight.discard(task)
        self._semaphore.release()
        if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
            logger.error("Task execution error: %s", task.exception())

"""Tests for service.tasks.runner.BackgroundTaskRunner."""

import asyncio
import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.tasks.models import BackgroundTask, TaskStatus
from service.tasks.registry import task_handler, get_handler
from service.tasks.runner import BackgroundTaskRunner


@pytest.fixture
async def task_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(BackgroundTask.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def task_sf(task_engine):
    return async_sessionmaker(
        bind=task_engine, autocommit=False, autoflush=False,
        expire_on_commit=False, class_=AsyncSession,
    )


@pytest.fixture
def runner(task_sf):
    return BackgroundTaskRunner(task_sf, poll_interval=0.1, batch_size=5, max_concurrent=2)


async def _insert_task(sf, task_type="test.task", status=TaskStatus.PENDING, **kwargs):
    defaults = dict(
        task_type=task_type, status=status, payload={},
        max_retries=3, scheduled_at=dt.datetime.now(dt.timezone.utc),
    )
    defaults.update(kwargs)
    task = BackgroundTask(**defaults)
    async with sf() as session:
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task


async def _get_task(sf, task_id):
    async with sf() as session:
        result = await session.execute(
            select(BackgroundTask).where(BackgroundTask.id == task_id)
        )
        return result.scalar_one_or_none()


# -- Lifecycle ----------------------------------------------------------------

class TestBackgroundTaskRunnerLifecycle:
    async def test_start_sets_running(self, runner):
        await runner.start()
        assert runner._running is True
        await runner.stop()

    async def test_start_idempotent(self, runner):
        await runner.start()
        task1 = runner._poll_task
        await runner.start()
        assert runner._poll_task is task1
        await runner.stop()

    async def test_stop_clears_running(self, runner):
        await runner.start()
        await runner.stop()
        assert runner._running is False


# -- Execution ----------------------------------------------------------------

class TestBackgroundTaskRunnerExecution:
    async def test_execute_task_success(self, runner, task_sf):
        _results = []

        @task_handler("test.success")
        async def handle(payload):
            _results.append(payload)
            return {"done": True}

        try:
            task = await _insert_task(
                task_sf, "test.success", status=TaskStatus.RUNNING, attempts=1
            )
            await runner._execute_task(task)
            updated = await _get_task(task_sf, task.id)
            assert updated.status == TaskStatus.COMPLETED
        finally:
            from service.tasks.registry import _HANDLERS
            _HANDLERS.pop("test.success", None)

    async def test_execute_task_no_handler(self, runner, task_sf):
        task = await _insert_task(task_sf, "test.missing", status=TaskStatus.RUNNING, attempts=1)
        await runner._execute_task(task)
        updated = await _get_task(task_sf, task.id)
        assert updated.status == TaskStatus.FAILED
        assert "No handler" in updated.error

    async def test_execute_task_retry(self, runner, task_sf):
        @task_handler("test.retry")
        async def handle(payload):
            raise RuntimeError("temporary failure")

        try:
            task = await _insert_task(
                task_sf, "test.retry", status=TaskStatus.RUNNING,
                attempts=1, max_retries=3,
            )
            await runner._execute_task(task)
            updated = await _get_task(task_sf, task.id)
            assert updated.status == TaskStatus.PENDING
        finally:
            from service.tasks.registry import _HANDLERS
            _HANDLERS.pop("test.retry", None)

    async def test_execute_task_exhausted(self, runner, task_sf):
        @task_handler("test.exhaust")
        async def handle(payload):
            raise RuntimeError("permanent failure")

        try:
            task = await _insert_task(
                task_sf, "test.exhaust", status=TaskStatus.RUNNING,
                attempts=3, max_retries=3,
            )
            await runner._execute_task(task)
            updated = await _get_task(task_sf, task.id)
            assert updated.status == TaskStatus.FAILED
        finally:
            from service.tasks.registry import _HANDLERS
            _HANDLERS.pop("test.exhaust", None)


# -- Mark methods -------------------------------------------------------------

class TestBackgroundTaskRunnerMarkers:
    async def test_mark_completed(self, runner, task_sf):
        task = await _insert_task(task_sf, status=TaskStatus.RUNNING)
        await runner._mark_completed(task, {"result": "ok"})
        updated = await _get_task(task_sf, task.id)
        assert updated.status == TaskStatus.COMPLETED

    async def test_mark_failed(self, runner, task_sf):
        task = await _insert_task(task_sf, status=TaskStatus.RUNNING)
        await runner._mark_failed(task, "something broke")
        updated = await _get_task(task_sf, task.id)
        assert updated.status == TaskStatus.FAILED
        assert "something broke" in updated.error

    async def test_mark_retry_backoff(self, runner, task_sf):
        task = await _insert_task(task_sf, status=TaskStatus.RUNNING, attempts=2)
        await runner._mark_retry(task, "retryable error")
        updated = await _get_task(task_sf, task.id)
        assert updated.status == TaskStatus.PENDING
        assert updated.scheduled_at is not None


# -- _task_done callback ------------------------------------------------------

class TestTaskDoneCallback:
    async def test_task_done_removes_from_inflight(self, runner):
        async def noop():
            pass

        t = asyncio.create_task(noop())
        runner._in_flight.add(t)
        await t
        runner._task_done(t)
        assert t not in runner._in_flight

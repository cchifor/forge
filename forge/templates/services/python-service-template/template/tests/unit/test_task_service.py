"""Tests for service.tasks.service.TaskService."""

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.tasks.models import BackgroundTask, TaskStatus
from service.tasks.service import TaskService


@pytest.fixture
async def task_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(BackgroundTask.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def task_session_factory(task_engine):
    return async_sessionmaker(
        bind=task_engine, autocommit=False, autoflush=False,
        expire_on_commit=False, class_=AsyncSession,
    )


@pytest.fixture
def task_service(task_session_factory):
    return TaskService(session_factory=task_session_factory)


class TestTaskService:
    async def test_enqueue_returns_uuid(self, task_service):
        task_id = await task_service.enqueue("email.send", payload={"to": "a@b.com"})
        assert task_id is not None

    async def test_enqueue_with_schedule(self, task_service):
        scheduled = dt.datetime(2030, 1, 1)
        task_id = await task_service.enqueue("report.generate", scheduled_at=scheduled)
        task = await task_service.get(task_id)
        assert task is not None
        assert task.scheduled_at.year == 2030

    async def test_get_existing(self, task_service):
        task_id = await task_service.enqueue("test.task")
        task = await task_service.get(task_id)
        assert task is not None
        assert task.task_type == "test.task"
        assert task.status == TaskStatus.PENDING

    async def test_get_nonexistent(self, task_service):
        import uuid
        result = await task_service.get(uuid.uuid4())
        assert result is None

    async def test_cancel_pending(self, task_service):
        task_id = await task_service.enqueue("test.cancel")
        cancelled = await task_service.cancel(task_id)
        assert cancelled is True

    async def test_cancel_non_pending(self, task_service, task_session_factory):
        task_id = await task_service.enqueue("test.running")
        # Manually set to RUNNING
        async with task_session_factory() as session:
            from sqlalchemy import update
            await session.execute(
                update(BackgroundTask)
                .where(BackgroundTask.id == task_id)
                .values(status=TaskStatus.RUNNING)
            )
            await session.commit()
        cancelled = await task_service.cancel(task_id)
        assert cancelled is False

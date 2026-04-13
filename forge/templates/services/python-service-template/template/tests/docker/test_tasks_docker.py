"""Test background tasks against real PostgreSQL."""

import uuid

import pytest
from sqlalchemy import select

from service.tasks.models import BackgroundTask, TaskStatus

pytestmark = pytest.mark.docker


class TestBackgroundTasksDocker:
    async def test_create_task(self, docker_session):
        """Create a background task in real PostgreSQL."""
        task = BackgroundTask(
            id=uuid.uuid4(),
            task_type="test.echo",
            status=TaskStatus.PENDING,
            payload={"message": "hello"},
        )
        docker_session.add(task)
        await docker_session.flush()
        assert task.id is not None

    async def test_task_status_enum(self, docker_session):
        """TaskStatus string enum works with PostgreSQL."""
        task = BackgroundTask(
            id=uuid.uuid4(),
            task_type="test.process",
            status=TaskStatus.RUNNING,
        )
        docker_session.add(task)
        await docker_session.flush()

        result = await docker_session.execute(
            select(BackgroundTask).where(BackgroundTask.id == task.id)
        )
        assert result.scalar_one().status == "RUNNING"

    async def test_task_json_payload(self, docker_session):
        """Task JSON payload roundtrips through PostgreSQL."""
        payload = {"key": "value", "nested": {"a": 1}}
        task = BackgroundTask(
            id=uuid.uuid4(),
            task_type="test.json",
            payload=payload,
        )
        docker_session.add(task)
        await docker_session.flush()

        result = await docker_session.execute(
            select(BackgroundTask).where(BackgroundTask.id == task.id)
        )
        assert result.scalar_one().payload == payload

    async def test_task_defaults(self, docker_session):
        """Task has correct defaults after insert."""
        task = BackgroundTask(
            id=uuid.uuid4(),
            task_type="test.defaults",
        )
        docker_session.add(task)
        await docker_session.flush()

        result = await docker_session.execute(
            select(BackgroundTask).where(BackgroundTask.id == task.id)
        )
        found = result.scalar_one()
        assert found.attempts == 0
        assert found.max_retries == 3
        assert found.status == TaskStatus.PENDING

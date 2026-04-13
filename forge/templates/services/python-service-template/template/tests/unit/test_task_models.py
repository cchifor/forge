"""Tests for the background-task ORM model and TaskStatus enum."""

from __future__ import annotations

from sqlalchemy import inspect

from service.tasks.models import BackgroundTask, TaskStatus


class TestTaskStatus:
    def test_expected_values(self):
        assert set(TaskStatus) == {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }

    def test_str_enum_string_value(self):
        assert str(TaskStatus.PENDING) == "PENDING"
        assert TaskStatus.FAILED == "FAILED"


class TestBackgroundTask:
    def test_tablename(self):
        assert BackgroundTask.__tablename__ == "background_tasks"

    def test_expected_columns(self):
        mapper = inspect(BackgroundTask)
        col_names = {c.key for c in mapper.column_attrs}
        for col in ("id", "task_type", "status", "payload", "result",
                     "error", "attempts", "max_retries", "scheduled_at",
                     "started_at", "completed_at", "created_at"):
            assert col in col_names, f"missing column: {col}"

    def test_status_scheduled_index(self):
        table = BackgroundTask.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_bg_tasks_status_scheduled" in index_names

    def test_nullable_constraints(self):
        table = BackgroundTask.__table__
        assert table.c.task_type.nullable is False
        assert table.c.status.nullable is False
        assert table.c.payload.nullable is True
        assert table.c.error.nullable is True

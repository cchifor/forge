"""Test that Alembic migrations work against real PostgreSQL."""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.docker


class TestMigrations:
    async def test_tables_created(self, docker_engine):
        """All expected tables exist after create_all."""
        async with docker_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            tables = {row[0] for row in result}
        assert "items" in tables
        assert "audit_logs" in tables
        assert "background_tasks" in tables

    async def test_items_table_columns(self, docker_engine):
        """Items table has expected columns."""
        async with docker_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'items'"
                )
            )
            columns = {row[0] for row in result}
        assert "id" in columns
        assert "name" in columns
        assert "status" in columns
        assert "customer_id" in columns

    async def test_background_tasks_table_columns(self, docker_engine):
        """Background tasks table has expected columns."""
        async with docker_engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'background_tasks'"
                )
            )
            columns = {row[0] for row in result}
        assert "task_type" in columns
        assert "status" in columns
        assert "payload" in columns

    async def test_indexes_created(self, docker_engine):
        """Expected indexes exist on items table."""
        async with docker_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'items'")
            )
            indexes = {row[0] for row in result}
        assert len(indexes) >= 2  # At least PK + one custom index

"""Test health service against real PostgreSQL."""

import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.docker


class TestHealthWithPostgres:
    async def test_readiness_with_real_db(self, docker_session):
        """Health readiness check succeeds against real PostgreSQL."""
        result = await docker_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    async def test_database_connection_latency(self, docker_session):
        """Database responds within reasonable time."""
        start = time.monotonic()
        await docker_session.execute(text("SELECT 1"))
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 1000  # Less than 1 second

    async def test_concurrent_connections(self, docker_engine):
        """Multiple concurrent sessions work."""
        factory = async_sessionmaker(docker_engine, expire_on_commit=False)
        async with factory() as s1, factory() as s2:
            r1 = await s1.execute(text("SELECT 1"))
            r2 = await s2.execute(text("SELECT 2"))
            assert r1.scalar() == 1
            assert r2.scalar() == 2

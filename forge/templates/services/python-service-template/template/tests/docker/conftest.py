"""Docker-based test fixtures using testcontainers."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.data.models import Base


@pytest.fixture(scope="session")
def postgres_url():
    """Start a real PostgreSQL container and return its async connection URL."""
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_url = pg.get_connection_url()
        async_url = sync_url.replace("psycopg2", "asyncpg")
        yield async_url


@pytest.fixture(scope="session")
async def docker_engine(postgres_url):
    """Create async engine connected to the real PostgreSQL container."""
    engine = create_async_engine(postgres_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def docker_session(docker_engine):
    """Provide an async session with automatic rollback after each test."""
    factory = async_sessionmaker(docker_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()

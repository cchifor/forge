"""Docker-based test fixtures using testcontainers."""

from __future__ import annotations

import shutil

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.data.models import Base


@pytest.fixture(scope="session")
def postgres_url():
    """Start a real PostgreSQL container and return its async connection URL.

    Skips the entire docker test suite when docker isn't available or when
    spinning up the container fails (e.g., flaky CI runner, image-pull
    timeout, port collision). The whole-session ``pytest.skip`` keeps
    ``pytest -v`` exit-clean instead of erroring 17 fixtures' worth of
    cascading setup failures.
    """
    if shutil.which("docker") is None:
        pytest.skip("docker not on PATH — skipping testcontainers-backed docker tests")
    # ``pgvector/pgvector:pg16`` is the upstream postgres + pgvector image —
    # fragments that need vector types (rag_pipeline / vector_store_postgres)
    # would crash on plain ``postgres:16-alpine`` with ``type "vector" does
    # not exist``. Plain installs that don't enable a vector backend
    # ignore the extra extension at zero migration cost.
    try:
        with PostgresContainer("pgvector/pgvector:pg16") as pg:
            sync_url = pg.get_connection_url()
            async_url = sync_url.replace("psycopg2", "asyncpg")
            yield async_url
    except Exception as exc:  # noqa: BLE001 — testcontainers raises a wide range
        pytest.skip(f"could not start postgres testcontainer: {exc}")


@pytest.fixture
async def docker_engine(postgres_url):
    """Create async engine connected to the real PostgreSQL container.

    Scoped per-test because asyncpg connection pools are bound to the event
    loop they were created in; pytest-asyncio in ``auto`` mode runs each test
    in its own function-scoped loop, so a session-scoped engine would raise
    ``got Future attached to a different loop``.
    """
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

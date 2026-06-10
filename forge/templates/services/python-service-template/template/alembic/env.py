import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.data.models import Base  # noqa: F401 — registers all models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    settings = get_settings()
    return settings.db.url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# A fixed, project-stable key for the migration advisory lock. Any concurrent
# replica running ``alembic upgrade head`` contends on this same key, so they
# serialize instead of racing the same DDL.
_MIGRATION_LOCK_KEY = 0x46_4F_52_47_45  # "FORGE"


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        # Serialize concurrent replicas: pg_advisory_xact_lock blocks until the
        # lock is free and auto-releases when this migration transaction ends.
        # The second replica then re-runs the (idempotent) upgrade, which is a
        # no-op for already-applied revisions. SQLite dev paths skip — they are
        # single-process. (Without this, the entrypoint comment promising a
        # lock was false and two replicas could apply the same DDL at once.)
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql(
                f"SELECT pg_advisory_xact_lock({_MIGRATION_LOCK_KEY})"
            )
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""The async engine + session-factory wrapper.

:class:`AsyncDatabase` owns a single ``AsyncEngine`` and the
``async_sessionmaker`` bound to it — one engine, one pool, shared across the
application. Construct it directly or from a config dict
(:meth:`AsyncDatabase.from_config`), hand its :attr:`session_factory` to the
unit of work / DI container, and :meth:`dispose` it on shutdown.
"""

from __future__ import annotations

import logging
from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from forge_core.persistence.config import build_engine_args, obfuscate_url

logger = logging.getLogger(__name__)


class AsyncDatabase:
    """Owns the async engine and the session factory bound to it."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        # Allow an AsyncDatabase to be carried as a field on a pydantic model
        # (e.g. an app context) without pydantic trying to validate its shape.
        from pydantic_core import core_schema

        return core_schema.is_instance_schema(cls)

    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = -1,
        echo: bool = False,
        application_name: str | None = None,
        ssl_mode: str | None = None,
        connect_args: dict[str, Any] | None = None,
    ) -> None:
        engine_args = build_engine_args(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            echo=echo,
            application_name=application_name,
            ssl_mode=ssl_mode,
            connect_args=connect_args,
            is_async=True,
        )

        self._engine: AsyncEngine = create_async_engine(url, **engine_args)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        logger.info("Async engine initialized for: %s", obfuscate_url(url))

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Self:
        """Build from a config mapping (e.g. ``settings.db.model_dump()``)."""
        return cls(**config)

    async def dispose(self) -> None:
        """Close the engine's connection pool (call on shutdown)."""
        await self._engine.dispose()

    async def check_connection(self) -> bool:
        """Return ``True`` if a trivial ``SELECT 1`` round-trips."""
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.error("Async DB health check failed: %s", exc)
            return False

import logging
from typing import Any, Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from service.db.config import build_engine_args, obfuscate_url

logger = logging.getLogger(__name__)


class AsyncDatabase:
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
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
            url=url,
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
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        logger.info(f"Async Engine initialized for: {obfuscate_url(url)}")

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Self:
        return cls(**config)

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def check_connection(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Async DB Health Check Failed: {e}")
            return False

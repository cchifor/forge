"""Infrastructure providers: database, discovery, sessions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable

from dishka import Provider, Scope, from_context, provide
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from service.db.aio import AsyncDatabase
from service.discovery import Discovery

logger = logging.getLogger(__name__)


class InfraProvider(Provider):
    """Database, discovery, and session factory."""

    scope = Scope.APP

    settings = from_context(provides=Settings, scope=Scope.APP)

    request = from_context(provides=Request, scope=Scope.REQUEST)

    @provide
    async def get_discovery(self, settings: Settings) -> AsyncIterable[Discovery]:
        if not settings.discovery.enabled:
            logger.info("Service discovery disabled.")
            yield Discovery(**settings.discovery.model_dump())
            return

        discovery = Discovery(**settings.discovery.model_dump())
        await discovery.register_async()
        yield discovery
        await discovery.unregister_async()

    @provide
    async def get_database(self, settings: Settings) -> AsyncIterable[AsyncDatabase]:
        db = AsyncDatabase.from_config(settings.db.model_dump())
        yield db
        await db.dispose()

    @provide
    def get_session_factory(self, db: AsyncDatabase) -> async_sessionmaker:
        return db.session_factory

    @provide(scope=Scope.REQUEST)
    async def get_db_session(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> AsyncIterable[AsyncSession]:
        session = session_factory()
        try:
            yield session
        finally:
            await asyncio.shield(session.close())

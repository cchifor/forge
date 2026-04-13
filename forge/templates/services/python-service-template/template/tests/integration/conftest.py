"""Integration test fixtures.

Creates an in-memory SQLite database, auto-creates tables,
and provides an httpx AsyncClient with overridden DI.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
from app.core.errors import (
    ApplicationError,
    domain_exception_handler,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.ioc.security import AuthUnitOfWork, PublicUnitOfWork
from app.data.models import Base
from app.services.health_service import HealthService
from app.services.item_service import ItemService
from service.domain.account import Account
from service.domain.user import User
from service.tasks.service import TaskService
from service.uow.aio import AsyncUnitOfWork

os.environ["ENV"] = "testing"

FAKE_USER = User(
    id="00000000-0000-0000-0000-000000000001",
    username="test-user",
    email="test@example.com",
    first_name="Test",
    last_name="User",
    roles=["admin"],
    customer_id="00000000-0000-0000-0000-000000000001",
    org_id=None,
    token={},
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def session_factory(async_engine):
    return async_sessionmaker(
        bind=async_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@pytest.fixture
def test_account():
    return Account(
        customer_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000001",
    )


class TestProvider(Provider):
    """Overrides DI for tests: provides in-memory DB session and fake user."""

    scope = Scope.APP

    def __init__(self, session_factory, account):
        super().__init__()
        self._session_factory = session_factory
        self._account = account

    @provide
    def get_health_service(self) -> HealthService:
        return HealthService()

    @provide(scope=Scope.REQUEST)
    def get_user(self) -> User:
        return FAKE_USER

    @provide(scope=Scope.REQUEST)
    def get_auth_uow(self) -> AuthUnitOfWork:
        uow = AsyncUnitOfWork(session_factory=self._session_factory, account=self._account)
        return AuthUnitOfWork(uow)

    @provide(scope=Scope.REQUEST)
    def get_public_uow(self) -> PublicUnitOfWork:
        uow = AsyncUnitOfWork(session_factory=self._session_factory, account=None)
        return PublicUnitOfWork(uow)

    @provide(scope=Scope.REQUEST)
    def get_item_service(self, auth_uow: AuthUnitOfWork) -> ItemService:
        return ItemService(uow=auth_uow)

    @provide
    def get_task_service(self) -> TaskService:
        return TaskService(session_factory=self._session_factory)

    @provide(scope=Scope.REQUEST)
    def get_session_factory(self) -> async_sessionmaker:
        return self._session_factory


@pytest.fixture
async def test_app(session_factory, test_account) -> AsyncGenerator[FastAPI, None]:
    app = FastAPI()

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(ApplicationError, domain_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    app.include_router(api_router, prefix="/api/v1")

    container = make_async_container(TestProvider(session_factory, test_account))
    setup_dishka(container, app)

    yield app

    await container.close()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

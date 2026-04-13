import asyncio
from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar, cast, overload

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from service.domain.account import Account
from service.repository import AsyncBaseRepository

TModel = TypeVar("TModel", bound=DeclarativeBase)
TSchema = TypeVar("TSchema", bound=BaseModel)
TRepo = TypeVar("TRepo")

AsyncSessionFactory = Callable[[], AsyncSession]


class AsyncUnitOfWork:
    """Asynchronous Unit of Work. Manages session lifecycle and repository caching."""

    def __init__(self, session_factory: AsyncSessionFactory, account: Account | None = None):
        self._session_factory = session_factory
        self._account = account
        self._session: AsyncSession | None = None
        self._repositories: dict[str, Any] = {}

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("AsyncUnitOfWork is not active. Use 'async with uow:'")
        return self._session

    async def __aenter__(self) -> "AsyncUnitOfWork":
        self._session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if not self._session:
            return
        try:
            if exc_type:
                await self._session.rollback()
            else:
                await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        finally:
            await asyncio.shield(self._session.close())
            self._session = None
            self._repositories.clear()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def flush(self) -> None:
        await self.session.flush()

    @overload
    def repo(
        self, model: type[TModel], schema: type[TSchema], /
    ) -> AsyncBaseRepository[TModel, TSchema, TSchema, TSchema]: ...

    @overload
    def repo(self, repository_type: type[TRepo], /) -> TRepo: ...

    def repo(
        self,
        arg1: type[TModel] | type[TRepo],
        arg2: type[TSchema] | None = None,
    ) -> AsyncBaseRepository | TRepo:
        if isinstance(arg1, type) and arg2 is None:
            repo_cls = arg1
            key = f"custom_{repo_cls.__name__}"
            if key in self._repositories:
                return cast(TRepo, self._repositories[key])
            if issubclass(repo_cls, AsyncBaseRepository):
                self._repositories[key] = repo_cls(session=self.session, account=self._account)  # type: ignore
            else:
                self._repositories[key] = repo_cls(session=self.session)  # type: ignore
            return cast(TRepo, self._repositories[key])
        elif arg2 is not None:
            model = arg1
            schema = arg2
            key = f"generic_{model.__name__}"
            if key not in self._repositories:
                self._repositories[key] = AsyncBaseRepository(
                    session=self.session,
                    model=model,  # type: ignore
                    schema=schema,  # type: ignore
                    account=self._account,
                )
            return self._repositories[key]
        else:
            raise ValueError("Invalid arguments passed to uow.repo()")


class HealthRepository:
    """Standalone repository for infrastructure checks."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def ping_db(self) -> bool:
        try:
            await self.session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

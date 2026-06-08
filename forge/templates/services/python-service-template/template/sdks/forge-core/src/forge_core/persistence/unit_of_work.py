"""The async Unit of Work, the RLS tenant-scoping seam, and the health repo.

:class:`AsyncUnitOfWork` manages the session lifecycle (one session per
``async with`` block, commit on clean exit, rollback on exception) and caches
repositories created within the block.

Tenant scoping is **opt-in and generic**. When the UoW is constructed with an
account that carries a ``customer_id``, ``__aenter__`` binds that id to a
Postgres GUC (default :data:`DEFAULT_TENANT_GUC` = ``app.current_tenant``) so
Row-Level Security policies scope every query in the transaction. The GUC name
is a constructor parameter — a project that uses a different name passes it
once — and the whole mechanism is a no-op on non-Postgres dialects. A
non-multitenant project simply constructs the UoW without an account (or with
an account whose ``customer_id`` is ``None``) and never touches this path.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, TypeVar, cast, overload

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from forge_core.persistence.account import AccountProtocol
from forge_core.persistence.repository import AsyncBaseRepository

TModel = TypeVar("TModel", bound=DeclarativeBase)
TSchema = TypeVar("TSchema", bound=BaseModel)
TRepo = TypeVar("TRepo")

AsyncSessionFactory = Callable[[], AsyncSession]

# The default Postgres GUC the tenant id is bound to for Row-Level Security.
# Kept as ``app.current_tenant`` to align with forge's multitenancy feature
# (which binds the same GUC); override per-project via the ``tenant_guc``
# constructor parameter.
DEFAULT_TENANT_GUC = "app.current_tenant"


async def set_tenant_context(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    tenant_guc: str = DEFAULT_TENANT_GUC,
) -> None:
    """Scope ``session`` to a tenant for Postgres RLS (no-op off Postgres).

    Emits ``SELECT set_config(:guc, :t, true)`` — the ``true`` third argument
    scopes the GUC to the current transaction (compatible with a transaction-
    mode connection pooler). On non-Postgres dialects this returns without
    touching the session, so callers don't need a dialect check.
    """
    bind = session.bind
    dialect = bind.dialect.name if bind else ""
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config(:guc, :t, true)"),
        {"guc": tenant_guc, "t": str(tenant_id)},
    )


@asynccontextmanager
async def tenant_scoped_session(
    session_factory: AsyncSessionFactory,
    tenant_id: uuid.UUID,
    *,
    tenant_guc: str = DEFAULT_TENANT_GUC,
):
    """Open a session with the tenant GUC bound (for code outside the UoW).

    Workers / background tasks that use a ``session_factory`` directly get the
    same RLS binding the UoW applies on enter, without their own boilerplate.
    """
    session = session_factory()
    try:
        await set_tenant_context(session, tenant_id, tenant_guc=tenant_guc)
        yield session
    finally:
        await asyncio.shield(session.close())


class AsyncUnitOfWork:
    """Async Unit of Work: session lifecycle, repository cache, opt-in RLS."""

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        account: AccountProtocol | None = None,
        *,
        tenant_guc: str = DEFAULT_TENANT_GUC,
        outbox_sink: Callable[[AsyncSession, Sequence[Any]], Any] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._account = account
        self._tenant_guc = tenant_guc
        # Optional pluggable sink flushed (in-transaction) at commit. Decoupled
        # from any event implementation: a project that emits domain events
        # supplies a sink; the base persistence layer ships none.
        self._outbox_sink = outbox_sink
        self._session: AsyncSession | None = None
        self._repositories: dict[str, Any] = {}
        self._pending_events: list[Any] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("AsyncUnitOfWork is not active. Use 'async with uow:'")
        return self._session

    async def __aenter__(self) -> AsyncUnitOfWork:
        self._session = self._session_factory()
        await self._apply_session_gucs(self._session)
        return self

    async def _apply_session_gucs(self, session: AsyncSession) -> None:
        """Hook: bind session-level Postgres GUCs for RLS.

        Default behaviour scopes the session by the account's ``customer_id``
        via the configured tenant GUC. A project with a different RLS schema
        subclasses the UoW and overrides this method only. No-op when there's
        no account / no tenant id, and on non-Postgres dialects.
        """
        if self._account is not None and self._account.customer_id is not None:
            await set_tenant_context(
                session, self._account.customer_id, tenant_guc=self._tenant_guc
            )

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
                await self._flush_pending_events()
                await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        finally:
            await asyncio.shield(self._session.close())
            self._session = None
            self._repositories.clear()
            self._pending_events.clear()

    def collect_event(self, event: Any) -> None:
        """Buffer a domain event to be flushed (in-transaction) at commit.

        Requires an ``outbox_sink`` to have been supplied at construction;
        buffered events are dropped on rollback. The base persistence layer
        ships no sink — this is the seam an events feature plugs into.
        """
        if self._session is None:
            raise RuntimeError("collect_event requires an active UoW. Use 'async with uow:'")
        if self._outbox_sink is None:
            raise RuntimeError("collect_event requires an outbox_sink on the AsyncUnitOfWork.")
        self._pending_events.append(event)

    async def _flush_pending_events(self) -> None:
        if not self._pending_events or self._outbox_sink is None:
            return
        await self._outbox_sink(self.session, list(self._pending_events))

    async def commit(self) -> None:
        try:
            await self._flush_pending_events()
            await self.session.commit()
        finally:
            self._pending_events.clear()

    async def rollback(self) -> None:
        try:
            await self.session.rollback()
        finally:
            self._pending_events.clear()

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
                self._repositories[key] = repo_cls(session=self.session, account=self._account)
            else:
                self._repositories[key] = repo_cls(session=self.session)
            return cast(TRepo, self._repositories[key])
        elif arg2 is not None:
            # The overloads guarantee ``arg1`` is the model type here; narrow
            # away the ``type[TRepo]`` arm so the generic ctor type-checks.
            model = cast("type[DeclarativeBase]", arg1)
            schema = arg2
            key = f"generic_{model.__name__}"
            if key not in self._repositories:
                self._repositories[key] = AsyncBaseRepository(
                    session=self.session,
                    model=model,
                    schema=schema,
                    account=self._account,
                )
            return self._repositories[key]
        else:
            raise ValueError("Invalid arguments passed to uow.repo()")


class HealthRepository:
    """Standalone repository for infrastructure / readiness checks."""

    def __init__(self, session: AsyncSession, *, tenant_guc: str = DEFAULT_TENANT_GUC) -> None:
        self.session = session
        self._tenant_guc = tenant_guc

    async def ping_db(self) -> bool:
        try:
            await self.session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def check_rls_guc(self) -> bool:
        """Readiness check: can the RLS tenant GUC be set? (no-op off Postgres).

        If the GUC can't be set — wrong DB grants, missing helper function —
        every tenant-scoped query against an RLS-enforced table returns empty.
        That fails closed but silently; this probe catches it loudly.
        """
        bind = self.session.bind
        dialect = bind.dialect.name if bind else ""
        if dialect != "postgresql":
            return True
        try:
            await self.session.execute(
                text("SELECT set_config(:guc, :t, true)"),
                {"guc": self._tenant_guc, "t": "00000000-0000-0000-0000-000000000000"},
            )
            return True
        except Exception:
            return False

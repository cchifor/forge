"""Real-Postgres integration test: schema-per-tenant cross-tenant isolation.

Shipped by ``database.multitenancy=schema_per_tenant``. Proves the actual
isolation property end to end against a live Postgres (the unit tests use a fake
session and can only assert the SQL shape):

- the UoW ``session_binder`` (:func:`bind_tenant_search_path`) routes a request's
  transaction to the authenticated tenant's schema, so a write under tenant A is
  invisible to tenant B (physical schema isolation);
- a request with no account (``PublicUnitOfWork``) fails closed — the engine
  ``begin`` listener binds an empty ``search_path`` so unqualified app tables
  don't resolve.

Requires a Postgres reachable at ``$TEST_DATABASE_URL`` (a
``postgresql+asyncpg://…`` URL). Skips otherwise, so it is inert in the default
SQLite-backed unit run and active wherever CI/dev provides a Postgres.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.tenancy.schema import (
    bind_tenant_search_path,
    provision_tenant_schema,
    register_search_path_listener,
)
from forge_core.persistence.unit_of_work import AsyncUnitOfWork

_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _URL.startswith("postgresql"),
        reason="set TEST_DATABASE_URL=postgresql+asyncpg://… to run the Postgres isolation test",
    ),
]


class _Account:
    def __init__(self, customer_id: str) -> None:
        self.customer_id = customer_id
        self.user_id = None


@pytest.mark.asyncio
async def test_schema_per_tenant_cross_tenant_isolation() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    engine = create_async_engine(_URL)
    register_search_path_listener(engine)  # always-on fail-closed default
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # A self-contained table materialized into each tenant schema (no coupling to
    # the project's models — this exercises the search_path routing itself).
    md = MetaData()
    Table("iso_probe", md, Column("id", Integer, primary_key=True), Column("v", String))

    def _uow(account: _Account | None) -> AsyncUnitOfWork:
        return AsyncUnitOfWork(
            session_factory=session_factory, account=account, session_binder=bind_tenant_search_path
        )

    try:
        await provision_tenant_schema(engine, tenant_a, metadata=md)
        await provision_tenant_schema(engine, tenant_b, metadata=md)

        # Write under tenant A.
        async with _uow(_Account(tenant_a)) as uow:
            await uow.session.execute(text("INSERT INTO iso_probe (v) VALUES ('a-secret')"))

        # Tenant A sees its row; tenant B sees NONE (physical isolation).
        async with _uow(_Account(tenant_a)) as uow:
            seen_a = (await uow.session.execute(text("SELECT count(*) FROM iso_probe"))).scalar()
        async with _uow(_Account(tenant_b)) as uow:
            seen_b = (await uow.session.execute(text("SELECT count(*) FROM iso_probe"))).scalar()
        assert seen_a == 1, "tenant A must see its own row"
        assert seen_b == 0, "tenant B must NOT see tenant A's row — cross-tenant leak"

        # No account (PublicUnitOfWork) ⇒ fail closed: empty search_path, the
        # unqualified table does not resolve.
        with pytest.raises(Exception):  # noqa: B017,PT011 — Postgres UndefinedTable
            async with _uow(None) as uow:
                await uow.session.execute(text("SELECT count(*) FROM iso_probe"))
    finally:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "tenant_{tenant_a}" CASCADE')
            await conn.exec_driver_sql(f'DROP SCHEMA IF EXISTS "tenant_{tenant_b}" CASCADE')
        await engine.dispose()

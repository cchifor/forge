"""Real-Postgres integration test: shared-RLS cross-tenant isolation.

Shipped by ``database.multitenancy=shared_rls``. Proves that the UoW binds
``app.current_tenant`` from the authenticated account (``set_tenant_context`` in
``__aenter__``) so a Row-Level-Security policy keyed on that GUC physically
filters cross-tenant rows — the token-claim tenant flows account → GUC → policy.

Requires a Postgres reachable at ``$TEST_DATABASE_URL`` (a
``postgresql+asyncpg://…`` URL); skips otherwise (inert in the SQLite unit run).
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from forge_core.persistence.unit_of_work import AsyncUnitOfWork

_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _URL.startswith("postgresql"),
        reason="set TEST_DATABASE_URL=postgresql+asyncpg://… to run the Postgres RLS test",
    ),
]


class _Account:
    def __init__(self, customer_id: str) -> None:
        self.customer_id = customer_id
        self.user_id = None


@pytest.mark.asyncio
async def test_shared_rls_cross_tenant_isolation() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    engine = create_async_engine(_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # RLS is bypassed by SUPERUSER / BYPASSRLS roles, so the policy can only be
    # validated as a normal role (which is what a generated app uses). Skip
    # rather than assert a false pass when connected as a bypassing role.
    async with engine.connect() as conn:
        bypasses = (
            await conn.exec_driver_sql(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).scalar()
    if bypasses:
        await engine.dispose()
        pytest.skip("connected as a SUPERUSER/BYPASSRLS role — RLS is bypassed; use the app role")

    # Self-contained RLS-protected table keyed on the app.current_tenant GUC —
    # the same predicate shape the shared_rls migration installs.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP TABLE IF EXISTS rls_probe")
        await conn.exec_driver_sql(
            "CREATE TABLE rls_probe (id serial PRIMARY KEY, customer_id uuid NOT NULL, v text)"
        )
        await conn.exec_driver_sql("ALTER TABLE rls_probe ENABLE ROW LEVEL SECURITY")
        await conn.exec_driver_sql("ALTER TABLE rls_probe FORCE ROW LEVEL SECURITY")
        await conn.exec_driver_sql(
            "CREATE POLICY rls_probe_tenant ON rls_probe "
            "USING (customer_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid) "
            "WITH CHECK (customer_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid)"
        )

    def _uow(account: _Account | None) -> AsyncUnitOfWork:
        # No session_binder: shared_rls uses the default account→GUC bind.
        return AsyncUnitOfWork(session_factory=session_factory, account=account)

    try:
        # Write under tenant A (UoW binds app.current_tenant = A).
        async with _uow(_Account(tenant_a)) as uow:
            await uow.session.execute(
                text("INSERT INTO rls_probe (customer_id, v) VALUES (:c, 'a-secret')"),
                {"c": tenant_a},
            )

        async with _uow(_Account(tenant_a)) as uow:
            seen_a = (await uow.session.execute(text("SELECT count(*) FROM rls_probe"))).scalar()
        async with _uow(_Account(tenant_b)) as uow:
            seen_b = (await uow.session.execute(text("SELECT count(*) FROM rls_probe"))).scalar()
        assert seen_a == 1, "tenant A must see its own row"
        assert seen_b == 0, "tenant B must NOT see tenant A's row — RLS leak"

        # No tenant context (PublicUnitOfWork) ⇒ fail closed with ZERO rows.
        # The policy's ``NULLIF(current_setting(...), '')`` collapses both the
        # never-set (NULL) and reverted-empty ('') GUC to NULL, so the cast
        # never raises — even on a connection recycled from a prior tenant.
        async with _uow(None) as uow:
            seen_public = (
                await uow.session.execute(text("SELECT count(*) FROM rls_probe"))
            ).scalar()
        assert seen_public == 0, "no tenant context must not see tenant data (fail closed)"
    finally:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("DROP TABLE IF EXISTS rls_probe")
        await engine.dispose()

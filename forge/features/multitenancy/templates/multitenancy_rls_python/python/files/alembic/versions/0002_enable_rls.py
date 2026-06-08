"""Enable Postgres Row-Level Security for tenant isolation (shared_rls).

Revision ID: 0002_enable_rls
Revises: 0001
Create Date: 2026-06-05

Shipped by ``database.multitenancy=shared_rls``. Layers RLS on top of the
``customer_id`` columns the base template already declares (weld
``TenantMixin``): for every tenant-scoped table it enables Row-Level
Security and installs a policy restricting visible rows to the tenant bound
to the Postgres ``app.current_tenant`` GUC (set per request/transaction by
``app.core.tenancy.rls.TenantRLSHook``).

EVERYTHING here is IDEMPOTENT — safe to re-run:

- ``ALTER TABLE ... ENABLE ROW LEVEL SECURITY`` is guarded by a check
  against ``pg_class.relrowsecurity`` so a re-run is a no-op.
- ``CREATE POLICY`` is preceded by ``DROP POLICY IF EXISTS`` so a re-run
  drops + recreates rather than erroring on the duplicate.
- ``FORCE ROW LEVEL SECURITY`` makes the policy apply to the table owner
  too (the service role is typically the owner), closing the
  "owner bypasses RLS" gap.

The policy predicate is::

    USING (customer_id = current_setting('app.current_tenant', true)::uuid)
    WITH CHECK (customer_id = current_setting('app.current_tenant', true)::uuid)

``current_setting(..., true)`` returns NULL (rather than erroring) when the
GUC is unset, so an unbound connection sees zero rows instead of crashing —
fail-closed, never fail-open.

Postgres-only: the migration short-circuits to a no-op on any non-postgres
dialect so the same migration chain runs on SQLite test databases.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_enable_rls"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The Postgres GUC the per-request hook binds the tenant id to. MUST match
# ``app.core.tenancy.rls.TENANT_GUC``. Kept as a module constant so the policy
# predicate and the runtime hook can never drift.
TENANT_GUC = "app.current_tenant"

# The tenant-discriminator column installed by weld's ``TenantMixin`` on every
# tenant-scoped model. The RLS policy keys off this column.
TENANT_COLUMN = "customer_id"

# Tables that carry ``customer_id`` and must be tenant-isolated. The base
# template ships ``items`` + ``audit_logs`` with a ``customer_id`` column;
# ``background_tasks`` is intentionally NOT listed (it is an operational queue
# with no tenant column). Extend this tuple as tenant-scoped tables are added.
RLS_TABLES: tuple[str, ...] = ("items", "audit_logs")


def _enable_rls(table: str) -> None:
    """Enable + force RLS and (re)create the tenant policy for ``table``.

    Idempotent: ENABLE is guarded by ``pg_class.relrowsecurity``; the policy
    is dropped-if-exists before recreation. Wrapped in a DO block so the whole
    macro is a single re-runnable statement.
    """
    policy = f"tenant_isolation_{table}"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class
                WHERE relname = '{table}' AND relrowsecurity = true
            ) THEN
                EXECUTE 'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY';
            END IF;
            EXECUTE 'ALTER TABLE {table} FORCE ROW LEVEL SECURITY';
            EXECUTE 'DROP POLICY IF EXISTS {policy} ON {table}';
            EXECUTE 'CREATE POLICY {policy} ON {table} '
                || 'USING ({TENANT_COLUMN} = current_setting(''{TENANT_GUC}'', true)::uuid) '
                || 'WITH CHECK ({TENANT_COLUMN} = current_setting(''{TENANT_GUC}'', true)::uuid)';
        END
        $$;
        """
    )


def _disable_rls(table: str) -> None:
    """Drop the tenant policy and disable RLS for ``table`` (idempotent)."""
    policy = f"tenant_isolation_{table}"
    op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # RLS is a Postgres feature; on SQLite / other test dialects the
        # migration is a no-op so the chain still runs end-to-end.
        return
    for table in RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in RLS_TABLES:
        _disable_rls(table)

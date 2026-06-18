"""Enable Row-Level Security on tenant-scoped FEATURE tables (audit #3).

Feature fragments (conversation, file_upload, rag, webhooks) add models that
subclass weld's ``TenantMixin`` — so they carry the ``customer_id`` discriminator
— in their own table-creation migrations, but shipped NO RLS policy. Under
``database.multitenancy=shared_rls`` those tables must get the same ENABLE +
FORCE + tenant policy as the base ``items``/``audit_logs`` (see
``0002_enable_rls.py``), or any query that omits the ``customer_id`` predicate
leaks cross-tenant there while the same mistake on ``items`` is caught by RLS.

Two properties make this safe regardless of which features are enabled:

* **Runs last.** The high numeric filename prefix sorts after every feature's
  table-creation migration (``migration_chain`` orders by numeric prefix), so
  every enabled tenant table already exists when this runs.
* **Existence-guarded.** ``to_regclass`` is NULL for a table whose feature
  isn't enabled, so that table is silently skipped.

Idempotent + Postgres-only, mirroring the base RLS migration.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0099_enable_rls_feature_tables"
down_revision: str | None = "0002_enable_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# MUST match 0002_enable_rls.py + app.core.tenancy.rls so the policy predicate
# and the per-request GUC hook never drift.
TENANT_GUC = "app.current_tenant"
TENANT_COLUMN = "customer_id"

# Every feature model that subclasses ``TenantMixin``. Existence-guarded below,
# so listing a table whose feature is disabled is a safe no-op. Keep in sync
# with the TenantMixin feature models — tests/test_rls_feature_table_coverage.py
# fails if a new tenant-scoped feature table ships without coverage here.
FEATURE_RLS_TABLES: tuple[str, ...] = (
    "conversations",
    "conversation_messages",
    "conversation_tool_calls",
    "chat_files",
    "rag_document_chunks",
    "rag_pg_document_chunks",
    "webhooks",
)


def _enable_rls_if_exists(table: str) -> None:
    """ENABLE + FORCE RLS and (re)create the tenant policy for ``table`` if it
    exists. Idempotent (ENABLE guarded by ``pg_class.relrowsecurity``, policy
    dropped-if-exists) and existence-guarded (``to_regclass``). Wrapped in a DO
    block so the whole macro is a single re-runnable statement."""
    policy = f"tenant_isolation_{table}"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('{table}') IS NULL THEN
                RETURN;  -- feature table not present; nothing to isolate
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_class
                WHERE relname = '{table}' AND relrowsecurity = true
            ) THEN
                EXECUTE 'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY';
            END IF;
            EXECUTE 'ALTER TABLE {table} FORCE ROW LEVEL SECURITY';
            EXECUTE 'DROP POLICY IF EXISTS {policy} ON {table}';
            EXECUTE 'CREATE POLICY {policy} ON {table} '
                || 'USING ({TENANT_COLUMN} = NULLIF(current_setting(''{TENANT_GUC}'', true), '''')::uuid) '
                || 'WITH CHECK ({TENANT_COLUMN} = NULLIF(current_setting(''{TENANT_GUC}'', true), '''')::uuid)';
        END
        $$;
        """
    )


def _disable_rls_if_exists(table: str) -> None:
    """Drop the tenant policy + disable RLS for ``table`` if it exists."""
    policy = f"tenant_isolation_{table}"
    op.execute(
        f"""
        DO $$
        BEGIN
            IF to_regclass('{table}') IS NULL THEN
                RETURN;
            END IF;
            EXECUTE 'DROP POLICY IF EXISTS {policy} ON {table}';
            EXECUTE 'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY';
            EXECUTE 'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY';
        END
        $$;
        """
    )


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # RLS is a Postgres feature; on SQLite / other test dialects this is a
        # no-op so the chain still runs end-to-end.
        return
    for table in FEATURE_RLS_TABLES:
        _enable_rls_if_exists(table)


def downgrade() -> None:
    if not _is_postgres():
        return
    for table in FEATURE_RLS_TABLES:
        _disable_rls_if_exists(table)

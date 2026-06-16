"""Bind the resolved tenant id to the Postgres ``app.current_tenant`` GUC.

Shared-RLS tenancy needs the tenant id set on the *exact connection* a request
queries through, scoped to that request's transaction, with no leakage back
into the pool. The decoupled seam that achieves this without touching the
hand-written session provider is a **ContextVar + SQLAlchemy engine event
listener**:

1. The request middleware (:mod:`app.middleware.tenant_rls`) resolves the
   tenant and sets :data:`current_tenant_var`.
2. :func:`register_rls_listener` (called once at startup against the engine's
   sync engine) installs a ``"begin"`` listener that, on every transaction
   begin, reads :data:`current_tenant_var` and issues::

       SELECT set_config('app.current_tenant', '<tenant>', true)

   ``set_config(..., true)`` is the parameter-safe, transaction-local way to
   bind a GUC — the third ``true`` argument scopes it to the current
   transaction (a Postgres ``SET``-statement cannot take bind parameters, so a
   parameterized utility statement would render ``$1`` and raise a syntax error
   under asyncpg). The GUC auto-resets when the transaction ends — a pooled
   connection never carries one tenant's binding into the next request. When
   the ContextVar is unset the listener binds nothing, so
   ``current_setting(..., true)`` returns NULL and RLS fails closed (zero rows).

The GUC name is the module constant :data:`TENANT_GUC` and MUST match the RLS
policy migration (``alembic/versions/0002_enable_rls.py``).

NO-OP on non-Postgres dialects: :func:`register_rls_listener` only attaches the
listener for ``postgresql`` engines, so the template's SQLite-backed unit tests
run unchanged. The imperative :class:`TenantRLSHook` (an explicit
``await hook.bind(session, tenant)`` seam, for workers / tasks that run outside
the request middleware) likewise short-circuits off Postgres.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from app.core.tenancy.config import TenancySettings, get_tenancy_settings

logger = logging.getLogger(__name__)

# The Postgres GUC the tenant id is bound to. MUST match
# ``alembic/versions/0002_enable_rls.py``'s ``TENANT_GUC``.
TENANT_GUC = "app.current_tenant"

# Per-request tenant id, set by the middleware and read by the engine "begin"
# listener. ``None`` ⇒ bind nothing (RLS fails closed).
current_tenant_var: ContextVar[str | None] = ContextVar("current_tenant", default=None)


def register_rls_listener(engine: Any, settings: TenancySettings | None = None) -> bool:
    """Attach the tenant-GUC ``begin`` listener to ``engine`` (idempotent).

    ``engine`` is an SQLAlchemy ``AsyncEngine`` (the listener attaches to its
    ``.sync_engine``) or a plain sync ``Engine``. Returns ``True`` when the
    listener was attached (Postgres), ``False`` on non-Postgres dialects where
    RLS is a no-op.
    """
    cfg = settings or get_tenancy_settings()
    sync_engine = getattr(engine, "sync_engine", engine)
    if sync_engine.dialect.name != "postgresql":
        logger.debug("tenant_rls_listener_skip_non_postgres")
        return False

    from sqlalchemy import event, text  # noqa: PLC0415 — generated-project runtime dep

    guc = cfg.guc

    @event.listens_for(sync_engine, "begin")
    def _set_tenant_on_begin(conn: Any) -> None:  # pragma: no cover - exercised at runtime
        # Fires on every transaction begin against this engine. Reads the
        # request's tenant ContextVar and binds it LOCAL to the transaction.
        # set_config(..., true) is the parameter-safe, transaction-local form —
        # a Postgres SET-statement rejects bind params (asyncpg would render $1
        # and raise SQLSTATE 42601 at every BEGIN).
        tenant = current_tenant_var.get()
        if tenant is None:
            return
        conn.execute(
            text("SELECT set_config(:guc, :tenant, true)"),
            {"guc": guc, "tenant": str(tenant)},
        )

    return True


class TenantRLSHook:
    """Imperative GUC binder for code outside the request middleware.

    Workers / background tasks that open their own session (and therefore never
    pass through :class:`~app.middleware.tenant_rls.TenantRLSMiddleware`) call
    ``await hook.bind(session, tenant_id)`` after opening a transaction. No-op
    on non-Postgres dialects.
    """

    def __init__(self, settings: TenancySettings | None = None) -> None:
        self._settings = settings or get_tenancy_settings()

    @property
    def guc(self) -> str:
        return self._settings.guc

    @staticmethod
    def _is_postgres(session: Any) -> bool:
        try:
            return session.bind.dialect.name == "postgresql"
        except Exception:  # noqa: BLE001 — any introspection failure ⇒ no-op
            return False

    async def bind(self, session: Any, tenant_id: str | None) -> None:
        """Bind ``tenant_id`` to the GUC for the current transaction (LOCAL)."""
        if tenant_id is None:
            return
        if not self._is_postgres(session):
            logger.debug("tenant_rls_skip_non_postgres", extra={"tenant": tenant_id})
            return
        from sqlalchemy import text  # noqa: PLC0415

        await session.execute(
            text("SELECT set_config(:guc, :tenant, true)"),
            {"guc": self._settings.guc, "tenant": str(tenant_id)},
        )

    async def clear(self, session: Any) -> None:
        """Reset the GUC (defensive; LOCAL settings auto-reset on commit)."""
        if not self._is_postgres(session):
            return
        from sqlalchemy import text  # noqa: PLC0415

        await session.execute(
            text("SELECT set_config(:guc, '', true)"),
            {"guc": self._settings.guc},
        )


__all__ = [
    "TENANT_GUC",
    "TenantRLSHook",
    "current_tenant_var",
    "register_rls_listener",
]

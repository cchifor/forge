"""Route each request to its tenant's Postgres schema (schema_per_tenant).

Schema-per-tenant isolates tenants by giving each its own Postgres *schema*
(``tenant_<id>``) holding the full table set, instead of sharing one schema and
filtering rows by an RLS policy (the ``shared_rls`` strategy). The connection's
``search_path`` is bound, per request transaction, to the resolved tenant's
schema — so unqualified table references resolve to that tenant's tables and a
query can physically only touch one tenant's data.

The seam mirrors ``app.core.tenancy.rls`` exactly so the two strategies are
drop-in alternatives:

1. The request middleware (:mod:`app.middleware.tenant_schema`) resolves the
   tenant and sets :data:`current_tenant_var`.
2. :func:`register_search_path_listener` (called once at startup against the
   engine) installs a ``"begin"`` listener that, on every transaction begin,
   reads :data:`current_tenant_var` and issues::

       SET LOCAL search_path TO "tenant_<id>", public

   ``SET LOCAL`` scopes the change to the current transaction, so a pooled
   connection never carries one tenant's ``search_path`` into the next request.

Schema-name safety: :func:`schema_name_for` builds the schema name from a
configured prefix + the tenant id and ACCEPTS ONLY ``[A-Za-z0-9_-]`` tenant
ids (so UUIDs and slugs work, but no lossy substitution that could collide two
tenants onto one schema), enforces the Postgres 63-byte identifier limit, and
the name is double-quoted into the ``SET`` statement. Identifiers cannot be
bound as parameters, so this validate-then-quote path is the injection defense.

NO-OP on non-Postgres dialects: :func:`register_search_path_listener` only
attaches the listener for ``postgresql`` engines, so the template's
SQLite-backed unit tests run unchanged.

FAIL MODE differs from ``shared_rls``: RLS fails *closed* (an unbound GUC →
``current_setting(...) IS NULL`` → zero rows). Schema routing has no such
default — when no tenant is bound the ``search_path`` is left at its default
(``public``). Pair this strategy with auth so an unidentified request is
rejected (401) before it ever opens a transaction, and keep tenant rows out of
``public`` (it is the canonical/template schema, cloned per tenant by
:func:`provision_tenant_schema`). See ``SCHEMA_PER_TENANT.md``.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from typing import Any

from app.core.tenancy.config import (
    DEFAULT_SCHEMA_PREFIX,
    TenancyConfigError,
    TenancySettings,
    get_tenancy_settings,
)

logger = logging.getLogger(__name__)

# Per-request tenant id, set by the middleware and read by the engine "begin"
# listener. ``None`` ⇒ bind nothing (search_path left at its default).
current_tenant_var: ContextVar[str | None] = ContextVar("current_tenant", default=None)

# Tenant ids that may form a schema name. Allow-list (NOT a sanitizer): a
# lossy substitution could map two distinct tenants onto the same schema — a
# silent cross-tenant leak. Hyphens are allowed (UUIDs) and survive quoting.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Postgres truncates identifiers silently at 63 bytes; two long tenant ids
# could collide after truncation, so we reject rather than truncate.
_MAX_IDENTIFIER_BYTES = 63


def schema_name_for(tenant_id: Any, prefix: str = DEFAULT_SCHEMA_PREFIX) -> str:
    """Return the (validated) schema name for ``tenant_id``.

    Raises :class:`TenancyConfigError` when the tenant id is empty, carries a
    char outside ``[A-Za-z0-9_-]`` (which includes any surrounding whitespace),
    or the resulting name exceeds Postgres' 63-byte identifier limit.

    The mapping MUST be injective — two distinct tenant ids must never produce
    the same schema name, or one tenant reads/writes another's rows. So this
    does NOT ``strip()`` or ``lower()`` the id (both are lossy: ``" a "``/``"a"``
    and ``"A"``/``"a"`` would collapse). The id is validated and used verbatim;
    the result is double-quoted at the call site, so case is preserved
    (``tenant_A`` and ``tenant_a`` stay distinct schemas).
    """
    tid = str(tenant_id)
    if not tid or not _TENANT_ID_RE.match(tid):
        raise TenancyConfigError(
            f"tenant id {tenant_id!r} is not schema-safe; must be non-empty, "
            f"contain only [A-Za-z0-9_-], and carry no surrounding whitespace"
        )
    name = f"{prefix}{tid}"
    if len(name.encode("utf-8")) > _MAX_IDENTIFIER_BYTES:
        raise TenancyConfigError(
            f"schema name {name!r} exceeds the Postgres {_MAX_IDENTIFIER_BYTES}-byte "
            f"identifier limit ({len(name.encode('utf-8'))} bytes)"
        )
    return name


def _quote_ident(name: str) -> str:
    """Double-quote an identifier for a ``SET`` / ``CREATE SCHEMA`` statement."""
    return '"' + name.replace('"', '""') + '"'


def register_search_path_listener(engine: Any, settings: TenancySettings | None = None) -> bool:
    """Attach the per-transaction ``search_path`` ``begin`` listener to ``engine``.

    ``engine`` is an SQLAlchemy ``AsyncEngine`` (the listener attaches to its
    ``.sync_engine``) or a plain sync ``Engine``. Returns ``True`` when the
    listener was attached (Postgres), ``False`` on non-Postgres dialects where
    schema routing is a no-op.
    """
    cfg = settings or get_tenancy_settings()
    sync_engine = getattr(engine, "sync_engine", engine)
    if sync_engine.dialect.name != "postgresql":
        logger.debug("tenant_schema_listener_skip_non_postgres")
        return False

    from sqlalchemy import event  # noqa: PLC0415 — generated-project runtime dep

    prefix = cfg.schema_prefix

    @event.listens_for(sync_engine, "begin")
    def _set_search_path_on_begin(conn: Any) -> None:  # pragma: no cover - runtime
        # Fires on every transaction begin against this engine. Reads the
        # request's tenant ContextVar and routes the search_path LOCAL to the
        # transaction. A bad tenant id raises (the transaction fails) rather
        # than silently querying the wrong/shared schema.
        tenant = current_tenant_var.get()
        if tenant is None:
            return
        schema = schema_name_for(tenant, prefix)
        # ``, public`` keeps shared types/extensions resolvable, but it also
        # means an UN-provisioned tenant (whose schema lacks a table) falls
        # THROUGH to public.<table>. Provisioning MUST run before a tenant is
        # served, and ``public`` must hold no tenant rows. See SCHEMA_PER_TENANT.md.
        conn.exec_driver_sql(f"SET LOCAL search_path TO {_quote_ident(schema)}, public")

    return True


async def provision_tenant_schema(
    engine: Any,
    tenant_id: Any,
    *,
    metadata: Any,
    settings: TenancySettings | None = None,
) -> bool:
    """Create ``tenant_<id>`` and materialize the table set inside it (idempotent).

    ``CREATE SCHEMA IF NOT EXISTS`` then ``metadata.create_all`` with a
    ``schema_translate_map`` that redirects unqualified tables into the tenant
    schema. ``metadata`` is the project's declarative ``Base.metadata``. Returns
    ``True`` when the schema was provisioned (Postgres), ``False`` on a
    non-Postgres dialect (no-op — the SQLite dev/test path auto-creates tables
    in the single default schema).

    This is the bootstrap path; production deployments that track per-tenant
    migrations should run Alembic with ``version_table_schema=<schema>`` instead
    (see ``SCHEMA_PER_TENANT.md``).
    """
    cfg = settings or get_tenancy_settings()
    schema = schema_name_for(tenant_id, cfg.schema_prefix)
    sync_engine = getattr(engine, "sync_engine", engine)
    if sync_engine.dialect.name != "postgresql":
        logger.debug("tenant_schema_provision_skip_non_postgres", extra={"schema": schema})
        return False

    async with engine.begin() as conn:
        await conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(schema)}")
        await conn.run_sync(
            lambda sync_conn: metadata.create_all(
                sync_conn.execution_options(schema_translate_map={None: schema})
            )
        )
    logger.info("tenant_schema_provisioned", extra={"schema": schema})
    return True


class TenantSchemaHook:
    """Imperative ``search_path`` binder for code outside the request middleware.

    Workers / background tasks that open their own session (and therefore never
    pass through :class:`~app.middleware.tenant_schema.TenantSchemaMiddleware`)
    call ``await hook.bind(session, tenant_id)`` after opening a transaction.
    No-op on non-Postgres dialects.
    """

    def __init__(self, settings: TenancySettings | None = None) -> None:
        self._settings = settings or get_tenancy_settings()

    @property
    def schema_prefix(self) -> str:
        return self._settings.schema_prefix

    @staticmethod
    def _is_postgres(session: Any) -> bool:
        try:
            return session.bind.dialect.name == "postgresql"
        except Exception:  # noqa: BLE001 — any introspection failure ⇒ no-op
            return False

    async def bind(self, session: Any, tenant_id: Any | None) -> None:
        """Route the current transaction's ``search_path`` to ``tenant_id``'s schema."""
        if tenant_id is None:
            return
        if not self._is_postgres(session):
            logger.debug("tenant_schema_skip_non_postgres", extra={"tenant": tenant_id})
            return
        schema = schema_name_for(tenant_id, self._settings.schema_prefix)
        from sqlalchemy import text  # noqa: PLC0415

        # set_config(..., true) is LOCAL — auto-reset at transaction end. The
        # search_path VALUE is a bound parameter, but the schema name inside it
        # must still be a double-quoted identifier: a search_path list element
        # like a hyphenated UUID schema (tenant_<uuid>) is not a legal *unquoted*
        # identifier, so we quote it (schema_name_for already validated it).
        await session.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{_quote_ident(schema)}, public"},
        )

    async def clear(self, session: Any) -> None:
        """Reset the search_path to ``public`` (defensive; LOCAL auto-resets)."""
        if not self._is_postgres(session):
            return
        from sqlalchemy import text  # noqa: PLC0415

        await session.execute(text("SELECT set_config('search_path', 'public', true)"))


__all__ = [
    "TenantSchemaHook",
    "current_tenant_var",
    "provision_tenant_schema",
    "register_search_path_listener",
    "schema_name_for",
]

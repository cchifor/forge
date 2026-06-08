"""``database.multitenancy`` — tenant-isolation discriminator + resolution knobs.

The discriminator controls *how strongly* tenants are isolated in the
generated persistence layer:

- ``none`` (default): INERT. No new fragments, no output change. The base
  python-service-template is already tenant-*aware* via weld's
  ``TenantMixin`` / ``customer_id`` columns + ``TenantScopedRepository``;
  ``none`` adds no enforcement on top of that application-layer scoping.
- ``shared_rls``: Postgres Row-Level Security. One shared schema, one
  shared database; every tenant-scoped table gets ``ENABLE ROW LEVEL
  SECURITY`` + a ``USING (customer_id = current_setting('app.current_tenant'))``
  policy, and each request/transaction binds the GUC via a session hook.
  Python tier-1 (Postgres-only).
- ``schema_per_tenant`` / ``db_per_tenant``: KNOWN but DEFERRED. Validation
  accepts them (so a forge.toml that pins one is not rejected outright), but
  the resolver raises a clear "not yet implemented" error rather than
  silently generating a project with no isolation. See the resolver guard
  in ``forge/capability_resolver.py`` (``_check_multitenancy_deferred``).

Resolution sub-options drive *how* the per-request tenant id is discovered.
They compose with the just-landed auth ``ClaimMapper`` seam: with
``tenant_resolution=token_claim`` the GUC binder reads the tenant id from the
verified JWT claims using the same dot-path machinery the OIDC provider's
``ClaimMapper`` uses (``tenant_claim_path``); ``header`` reads a gateway-
injected header (``tenant_header_name``); ``subdomain`` parses the Host header.
"""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="database.multitenancy",
            type=OptionType.ENUM,
            default="none",
            options=("none", "shared_rls", "schema_per_tenant", "db_per_tenant"),
            summary="Tenant-isolation strategy for the generated persistence layer.",
            description="""\
Discriminator for how strongly tenants are isolated in the database.

- ``none`` (default): inert — no enforcement fragment is added. The base
  template stays tenant-*aware* (weld ``TenantMixin`` / ``customer_id``
  columns + ``TenantScopedRepository`` application-layer scoping) but no
  database-enforced isolation is layered on. Byte-identical to a project
  that never set this option.
- ``shared_rls``: Postgres Row-Level Security. One shared database + schema;
  every ``customer_id``-bearing table gets ``ENABLE ROW LEVEL SECURITY`` +
  a ``USING (customer_id = current_setting('app.current_tenant')::uuid)``
  policy (idempotent migration). A request middleware resolves the tenant
  (token claim / header / subdomain) and a session GUC hook binds
  ``app.current_tenant`` per transaction, so the database itself rejects
  cross-tenant reads/writes. Layers ON TOP of the existing TenantMixin —
  it adds the RLS policy + GUC binding + resolver, it does NOT re-add the
  ``customer_id`` column.
- ``schema_per_tenant`` / ``db_per_tenant``: recognised values but NOT yet
  implemented. forge accepts them in a forge.toml without rejecting the
  whole config, but generation fails with an explicit "not yet implemented"
  error rather than silently producing an un-isolated project. Use
  ``shared_rls`` today.

BACKENDS: python (shared_rls). The non-``none`` strategies are Python-only
in 1.x — the RLS GUC hook + Alembic policy macros target the SQLAlchemy /
Alembic stack the python-service-template ships.
ENGINE: postgres. The GUC hook is a no-op on non-Postgres dialects.""",
            category=FeatureCategory.PLATFORM,
            requires_database=True,
            # The non-``none`` strategies ship a Python-only realisation in
            # 1.x. ``allowed_backends`` is only enforced for an ACTIVE value
            # (``is_active_value`` — i.e. a value whose ``enables`` is
            # non-empty); ``none`` maps to no fragments so the default never
            # trips the check. Setting it here lets the resolver +
            # ProjectConfig walker reject e.g. ``shared_rls`` on a Node/Rust
            # project with a clear message instead of a runtime no-op.
            allowed_backends=(BackendLanguage.PYTHON,),
            enables={
                "shared_rls": ("multitenancy_rls_python",),
                # ``schema_per_tenant`` / ``db_per_tenant`` intentionally map
                # to no fragments — they are recognised-but-deferred. The
                # resolver's ``_check_multitenancy_deferred`` guard turns a
                # user selection of either into an explicit OptionsError so
                # the value never silently no-ops.
            },
        )
    )

    api.add_option(
        Option(
            path="database.tenant_resolution",
            type=OptionType.ENUM,
            default="token_claim",
            options=("token_claim", "header", "subdomain"),
            summary="How the per-request tenant id is discovered for RLS binding.",
            description="""\
Drives the ``TenantResolver`` shipped by ``database.multitenancy=shared_rls``.
Only meaningful when a non-``none`` strategy is selected (otherwise inert).

- ``token_claim`` (default): read the tenant id from the verified JWT claims
  via a dot-path (``database.tenant_claim_path``), reusing the auth
  ``ClaimMapper`` seam the OIDC / in_memory providers ship. The middleware
  reads ``request.state.identity`` (bound by the platform-auth middleware)
  and extracts the configured claim.
- ``header``: read the tenant id from a gateway-injected request header
  (``database.tenant_header_name``). For deployments where an upstream
  proxy / API gateway already resolved + validated the tenant.
- ``subdomain``: parse the leftmost label of the request Host header
  (``acme.example.com`` → ``acme``). For per-tenant subdomain routing.

BACKENDS: python. Inert unless ``database.multitenancy != none``.""",
            category=FeatureCategory.PLATFORM,
            requires_database=True,
        )
    )

    api.add_option(
        Option(
            path="database.tenant_claim_path",
            type=OptionType.STR,
            default="tenant_id",
            summary="Dot-path to the tenant id within the verified token claims.",
            description="""\
Used when ``database.tenant_resolution=token_claim``. A dot-path traversed
by the auth ``ClaimMapper`` (``organization.id`` reads
``claims['organization']['id']``; a literal URL-shaped claim name like
``https://example.com/tenant`` is matched as a whole key first). Defaults to
``tenant_id`` to match the platform-auth SDK's default tenant claim.

BACKENDS: python. Written into the generated ``TenantResolver`` config; no
fragment is keyed off the value.""",
            category=FeatureCategory.PLATFORM,
            requires_database=True,
        )
    )

    api.add_option(
        Option(
            path="database.tenant_header_name",
            type=OptionType.STR,
            default="X-Tenant-ID",
            summary="Request header carrying the tenant id (header resolution).",
            description="""\
Used when ``database.tenant_resolution=header``. The HTTP header the
``TenantResolver`` reads the tenant id from (case-insensitive). Defaults to
``X-Tenant-ID``.

BACKENDS: python. Written into the generated ``TenantResolver`` config; no
fragment is keyed off the value.""",
            category=FeatureCategory.PLATFORM,
            requires_database=True,
        )
    )

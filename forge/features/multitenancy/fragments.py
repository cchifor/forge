"""Multitenancy fragments — Postgres Row-Level Security for Python backends.

``multitenancy_rls_python`` realises ``database.multitenancy=shared_rls``. It
ships, per Python backend:

- a ``TenantResolver`` seam (``app/core/tenancy/resolver.py``) — resolve the
  per-request tenant id from a verified token claim (reusing the auth
  ``ClaimMapper`` dot-path seam), a request header, or the Host subdomain,
  driven by ``database.tenant_resolution`` + ``database.tenant_claim_path`` +
  ``database.tenant_header_name``;
- a ``TenantRLSHook`` seam (``app/core/tenancy/rls.py``) — bind the resolved
  tenant id to the Postgres ``app.current_tenant`` GUC for the lifetime of a
  session/transaction, with the GUC name a module constant
  (``TENANT_GUC``) and a no-op on non-Postgres dialects;
- request middleware (``app/middleware/tenant_rls.py``) — extract the tenant
  via the resolver and stash it for the GUC hook;
- an idempotent Alembic migration (``alembic/versions/0002_enable_rls.py``)
  that enables RLS + creates the per-table tenant policy via a re-runnable
  macro (``CREATE POLICY`` guarded by ``DROP POLICY IF EXISTS``,
  ``ENABLE ROW LEVEL SECURITY`` guarded by ``pg_class.relrowsecurity``).

The fragment reads ``database.tenant_resolution`` / ``database.tenant_claim_path``
/ ``database.tenant_header_name`` so the rendered resolver is configured for
the project's chosen strategy. It is backend-scoped + Python-only (parity tier
auto-derives to 3); the GUC-binding + Alembic RLS pattern targets the
SQLAlchemy/Alembic stack the python-service-template ships.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="multitenancy_rls_python",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("multitenancy_rls_python", "python"),
                    # Backend-scoped (default) — files land per Python backend.
                    env_vars=(
                        # The GUC name is a constant in code (TENANT_GUC) but
                        # surfaced as env for ops visibility / override.
                        ("TENANT_RLS_GUC", "app.current_tenant"),
                    ),
                    # The rendered resolver + middleware are configured from
                    # the chosen resolution strategy + claim/header names.
                    reads_options=(
                        "database.tenant_resolution",
                        "database.tenant_claim_path",
                        "database.tenant_header_name",
                    ),
                ),
            },
            # postgres-pgvector is overkill; plain postgres is provisioned by
            # database.mode=generate already. RLS needs no extra sidecar.
            capabilities=(),
        )
    )

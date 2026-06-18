"""Regression: schema_per_tenant fails closed for unprovisioned tenants (audit #29).

All three ``search_path`` binders (the engine ``begin`` listener,
``TenantSchemaHook.bind``, and the UoW ``bind_tenant_search_path``) appended
``, public`` unconditionally. Postgres ``search_path`` is ordered fall-through:
an authenticated tenant whose schema is NOT yet provisioned resolved an
unqualified ``FROM items`` to ``public.items`` (which exists from the base
migration), so a tenant served before ``provision_tenant_schema`` ran could
read/write the shared ``public`` tables — fail-OPEN cross-tenant, unlike the
no-tenant empty-search_path fail-closed branch.

Fix: each binder verifies the tenant schema exists (``to_regnamespace``) before
binding ``, public``; an unprovisioned tenant gets an empty search_path so
unqualified app tables error instead of falling through to ``public``.
"""

from __future__ import annotations

from pathlib import Path

_SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "forge/features/multitenancy/templates/multitenancy_schema_per_tenant_python/python"
    / "files/src/app/core/tenancy/schema.py"
)


def test_all_search_path_binders_fail_closed_when_schema_absent() -> None:
    src = _SCHEMA.read_text(encoding="utf-8")
    # All three binders must existence-check the tenant schema before binding.
    assert src.count("to_regnamespace") >= 3, (
        "every search_path binder must verify the tenant schema exists before "
        "binding ', public' (else an unprovisioned tenant falls through to public)"
    )
    # The unprovisioned path must fail closed (empty search_path), not public.
    assert "SET LOCAL search_path TO ''" in src

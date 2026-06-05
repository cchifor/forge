"""Tenant-isolation runtime: resolver + RLS GUC hook.

Shipped by ``database.multitenancy=shared_rls``. Public surface:

- :class:`~app.core.tenancy.config.TenancySettings` — env-driven config
  (resolution strategy, claim path, header name, GUC name).
- :class:`~app.core.tenancy.resolver.TenantResolver` — extract the
  per-request tenant id (token claim / header / subdomain).
- :class:`~app.core.tenancy.rls.TenantRLSHook` — bind the resolved tenant
  id to the Postgres ``app.current_tenant`` GUC for a session/transaction
  (no-op on non-Postgres dialects).
"""

from __future__ import annotations

from app.core.tenancy.config import TenancySettings, get_tenancy_settings
from app.core.tenancy.resolver import TenantResolver
from app.core.tenancy.rls import TENANT_GUC, TenantRLSHook

__all__ = [
    "TENANT_GUC",
    "TenancySettings",
    "TenantRLSHook",
    "TenantResolver",
    "get_tenancy_settings",
]

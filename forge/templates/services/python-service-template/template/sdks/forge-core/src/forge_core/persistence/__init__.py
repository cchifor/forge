"""forge-core persistence — a generic async SQLAlchemy persistence layer.

A self-contained (stdlib + SQLAlchemy + pydantic + :mod:`forge_core.errors`),
framework-agnostic persistence kit:

* :class:`AsyncDatabase` — the async engine + session factory.
* :class:`AsyncUnitOfWork` — session lifecycle, repository cache, opt-in RLS
  tenant scoping; :class:`HealthRepository` for readiness probes.
* :class:`AsyncBaseRepository` — generic CRUD over a model / schema pair,
  with tenant + owner + soft-delete scoping driven by the mixins.
* :class:`TimestampMixin`, :class:`TenantMixin`, :class:`UserOwnedMixin`,
  :class:`SoftDeleteMixin` — the declarative column patterns the repository
  scopes on.
* :class:`AccountProtocol` — the structural caller-identity contract the
  scoping is driven by (no dependency on any concrete identity model).

Tenant scoping is opt-in: the GUC name defaults to ``app.current_tenant``
(:data:`DEFAULT_TENANT_GUC`) but is a constructor parameter, and a
non-multitenant project never exercises the path.
"""

from forge_core.persistence.account import AccountProtocol
from forge_core.persistence.config import build_engine_args, obfuscate_url
from forge_core.persistence.database import AsyncDatabase
from forge_core.persistence.mixins import (
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UserOwnedMixin,
)
from forge_core.persistence.repository import (
    MAX_PAGE_SIZE,
    AsyncBaseRepository,
    RepositoryLogicMixin,
)
from forge_core.persistence.unit_of_work import (
    DEFAULT_TENANT_GUC,
    AsyncUnitOfWork,
    HealthRepository,
    set_tenant_context,
    tenant_scoped_session,
)

__all__ = [
    "DEFAULT_TENANT_GUC",
    "MAX_PAGE_SIZE",
    "AccountProtocol",
    "AsyncBaseRepository",
    "AsyncDatabase",
    "AsyncUnitOfWork",
    "HealthRepository",
    "RepositoryLogicMixin",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "UserOwnedMixin",
    "build_engine_args",
    "obfuscate_url",
    "set_tenant_context",
    "tenant_scoped_session",
]

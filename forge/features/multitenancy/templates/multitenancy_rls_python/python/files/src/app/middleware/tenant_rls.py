"""Request middleware: resolve the tenant and bind it for the RLS GUC hook.

Shipped by ``database.multitenancy=shared_rls``. On every request it runs the
:class:`~app.core.tenancy.resolver.TenantResolver` (token claim / header /
subdomain per config), stores the resolved tenant id on
``request.state.tenant_id`` for handlers/diagnostics, AND sets the
:data:`~app.core.tenancy.rls.current_tenant_var` ContextVar that the engine
``begin`` listener (installed by
:func:`~app.core.tenancy.rls.register_rls_listener` at startup) reads to issue
``SET LOCAL app.current_tenant`` on the request's transaction.

This middleware deliberately does NOT open a DB session itself — the GUC is
bound on the exact connection the request queries through, scoped to that
transaction, via the engine listener. The ContextVar is reset in a ``finally``
so a worker reusing the same task/thread never inherits a stale tenant.

Ordering: it must run AFTER the platform-auth middleware (which binds
``request.state.identity``) so ``token_claim`` resolution can read the verified
claims. ``database.multitenancy=shared_rls`` registers it after the auth
middleware at the ``FORGE:MIDDLEWARE_REGISTRATION`` marker.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.tenancy.resolver import TenantResolver
from app.core.tenancy.rls import current_tenant_var

# Where the resolved tenant id is stashed for handlers / diagnostics.
TENANT_STATE_KEY = "tenant_id"


class TenantRLSMiddleware(BaseHTTPMiddleware):
    """Resolve the per-request tenant id and bind it for the GUC listener."""

    def __init__(self, app: Any, resolver: TenantResolver | None = None) -> None:
        super().__init__(app)
        self._resolver = resolver

    def _resolver_for(self, request: Request) -> TenantResolver:
        # An explicit resolver (tests) always wins. Otherwise prefer the
        # option-driven settings the generator attached to app.state (see the
        # FORGE:APP_POST_CONFIGURE injection) so the project's chosen strategy
        # applies; fall back to env-driven settings when absent.
        if self._resolver is not None:
            return self._resolver
        settings = getattr(getattr(request.app, "state", None), "tenancy_settings", None)
        return TenantResolver(settings)

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        tenant_id = self._resolver_for(request).resolve(request)
        setattr(request.state, TENANT_STATE_KEY, tenant_id)
        token = current_tenant_var.set(tenant_id)
        try:
            return await call_next(request)
        finally:
            current_tenant_var.reset(token)


__all__ = ["TENANT_STATE_KEY", "TenantRLSMiddleware"]

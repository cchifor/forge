"""Regression: token_claim tenant resolution is post-auth-correct + honestly
documented (audit #15).

``TenantRLSMiddleware`` runs the resolver, which for ``token_claim`` read
``request.state.identity``. But in the generate-mode default, auth runs as a
FastAPI ROUTE DEPENDENCY (forge_core ``get_current_user``), not an outer
middleware — so ``request.state.identity`` is unset when the middleware runs
(it precedes route dependencies). The resolver therefore always returned
``None`` for token_claim, and the inject.yaml / docstrings falsely claimed an
auth middleware bound identity first. (Row isolation still held via the
account-scoped GUC the AsyncUnitOfWork binds independently, so this was a
dead-code / state-correctness defect, not a leak.)

Fix: the resolver falls back to forge_core's authoritative ``customer_id_context``
ContextVar (the verified tenant bound post-authentication), and the misleading
ordering comments are corrected.
"""

from __future__ import annotations

from pathlib import Path

_RLS = (
    Path(__file__).resolve().parent.parent
    / "forge/features/multitenancy/templates/multitenancy_rls_python/python"
)
_RESOLVER = _RLS / "files/src/app/core/tenancy/resolver.py"
_MIDDLEWARE = _RLS / "files/src/app/middleware/tenant_rls.py"
_INJECT = _RLS / "inject.yaml"


def test_resolver_falls_back_to_post_auth_tenant_context() -> None:
    resolver = _RESOLVER.read_text(encoding="utf-8")
    # The resolver must consult the authoritative post-auth tenant context, not
    # only request.state.identity (unset at middleware time for route-dep auth).
    assert "customer_id_context" in resolver, (
        "token_claim resolver must fall back to forge_core's customer_id_context "
        "(request.state.identity is unset when auth is a route dependency)"
    )


def test_false_middleware_ordering_premise_removed() -> None:
    inject = _INJECT.read_text(encoding="utf-8")
    middleware = _MIDDLEWARE.read_text(encoding="utf-8")
    # The false claim that an auth middleware binds identity before this resolver
    # must be gone from both the inject comment and the middleware docstring.
    assert "identity is bound before the resolver" not in inject
    assert "must run AFTER the platform-auth middleware" not in middleware
    # And the docs must state the real design (route-dependency auth).
    normalized = " ".join(middleware.lower().split())
    assert "route dependency" in normalized

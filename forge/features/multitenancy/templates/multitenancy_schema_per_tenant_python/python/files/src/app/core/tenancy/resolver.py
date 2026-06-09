"""Per-request tenant resolution.

The :class:`TenantResolver` extracts the tenant id for the current request via
the strategy configured in :class:`~app.core.tenancy.config.TenancySettings`:

- ``token_claim``: read the tenant id from the verified JWT claims bound on
  ``request.state.identity`` by the platform-auth middleware, using a dot-path
  (``TENANT_CLAIM_PATH``). This is the seam that COMPOSES with the auth
  ``ClaimMapper``: when the OIDC / in_memory provider's ``ClaimMapper`` is
  available on ``app.state`` (``oidc_claim_mapper``) it is reused so the exact
  same dot-path / whole-key resolution applies; otherwise a tiny built-in
  dot-path traversal (identical semantics) is used so the resolver works even
  for the gatekeeper provider, which binds an ``IdentityContext`` rather than a
  raw claims dict.
- ``header``: read the tenant id from a gateway-injected request header
  (``TENANT_HEADER_NAME``).
- ``subdomain``: parse the leftmost Host label (``acme.example.com`` →
  ``acme``).

A missing tenant resolves to ``None`` — the caller decides whether that is a
hard 401/403 or an anonymous/public request. This resolver drives the
``header``/``subdomain`` request-edge strategies (set on ``current_tenant_var``
for the engine listener). ``token_claim`` is bound separately, post-auth, from
the authenticated account by the UoW binder (``schema.py:bind_tenant_search_path``)
— it does NOT flow through this resolver at request time. See ``schema.py`` /
``SCHEMA_PER_TENANT.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.tenancy.config import TenancySettings, get_tenancy_settings

_UNSET = object()


def _dot_path(claims: Mapping[str, Any], path: str) -> Any:
    """Whole-key-then-dotted-traversal lookup.

    Mirrors the auth ``ClaimMapper.extract`` contract so a project that has no
    OIDC ``ClaimMapper`` on ``app.state`` (e.g. the gatekeeper provider) still
    resolves nested / URL-shaped claim names identically.
    """
    if path in claims:
        return claims[path]
    current: Any = claims
    for segment in path.split("."):
        if not isinstance(current, Mapping):
            return None
        nxt = current.get(segment, _UNSET)
        if nxt is _UNSET:
            return None
        current = nxt
    return current


class TenantResolver:
    """Resolve the per-request tenant id per the configured strategy."""

    def __init__(self, settings: TenancySettings | None = None) -> None:
        self._settings = settings or get_tenancy_settings()

    @property
    def settings(self) -> TenancySettings:
        return self._settings

    def resolve(self, request: Any) -> str | None:
        """Return the tenant id for ``request`` (a Starlette/FastAPI Request)."""
        strategy = self._settings.resolution
        if strategy == "header":
            return self._from_header(request)
        if strategy == "subdomain":
            return self._from_subdomain(request)
        return self._from_token_claim(request)

    # -- strategies ----------------------------------------------------------

    def _from_header(self, request: Any) -> str | None:
        value = request.headers.get(self._settings.header_name)
        return value or None

    def _from_subdomain(self, request: Any) -> str | None:
        host = request.headers.get("host", "")
        # Strip any :port suffix, then take the leftmost label.
        host = host.split(":", 1)[0].strip()
        if not host or "." not in host:
            return None
        label = host.split(".", 1)[0]
        return label or None

    def _from_token_claim(self, request: Any) -> str | None:
        identity = getattr(getattr(request, "state", None), "identity", None)
        if identity is None:
            return None
        claims = self._raw_claims(identity)
        if claims is not None:
            # Apply the configured claim path to the verified JWT claims,
            # reusing the provider's ClaimMapper when present (oidc/in_memory).
            mapper = self._claim_mapper(request)
            value = (
                mapper.extract(claims, path=self._settings.claim_path)
                if mapper is not None
                else _dot_path(claims, self._settings.claim_path)
            )
            if value is not None:
                return str(value)
        # No raw claims (e.g. gatekeeper binds an IdentityContext) or the claim
        # path missed — fall back to the identity's authoritative tenant id.
        tenant_id = getattr(identity, "tenant_id", None)
        return str(tenant_id) if tenant_id is not None else None

    # -- request introspection ----------------------------------------------

    @staticmethod
    def _raw_claims(identity: Any) -> Mapping[str, Any] | None:
        """Verified JWT claims dict, if the provider exposes one.

        forge's ``IdentityContext`` exposes ``.raw_claims``; some providers use
        ``.claims``. Returns ``None`` when neither is a mapping (e.g. gatekeeper
        binds an ``IdentityContext`` without raw claims — the caller then falls
        back to ``identity.tenant_id``).
        """
        for attr in ("raw_claims", "claims"):
            claims = getattr(identity, attr, None)
            if isinstance(claims, Mapping):
                return claims
        return None

    @staticmethod
    def _claim_mapper(request: Any) -> Any | None:
        app = getattr(request, "app", None)
        state = getattr(app, "state", None)
        return getattr(state, "oidc_claim_mapper", None)


__all__ = ["TenantResolver"]

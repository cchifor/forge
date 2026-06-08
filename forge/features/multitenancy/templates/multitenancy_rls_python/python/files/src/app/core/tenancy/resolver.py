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
hard 401/403 or an anonymous/public request. The GUC hook treats ``None`` as
"bind nothing", so RLS fails closed (an unbound connection sees zero rows).
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
        claims = self._claims_for(request)
        if not claims:
            return None
        # Reuse the auth ClaimMapper when the provider installed one on
        # app.state (oidc_generic / in_memory ship one). It carries the exact
        # dot-path / whole-key resolution the verifier was configured with.
        mapper = self._claim_mapper(request)
        if mapper is not None:
            value = mapper.extract(claims, path=self._settings.claim_path)
        else:
            value = _dot_path(claims, self._settings.claim_path)
        return str(value) if value is not None else None

    # -- request introspection ----------------------------------------------

    @staticmethod
    def _claims_for(request: Any) -> Mapping[str, Any] | None:
        """Best-effort fetch of the verified claims dict.

        The platform-auth middleware binds an identity on
        ``request.state.identity``; depending on provider it exposes the raw
        claims as ``.claims`` (verified JWT payload). When only an
        ``IdentityContext`` is present we fall back to its ``tenant_id``.
        """
        identity = getattr(getattr(request, "state", None), "identity", None)
        if identity is None:
            return None
        claims = getattr(identity, "claims", None)
        if isinstance(claims, Mapping):
            return claims
        tenant_id = getattr(identity, "tenant_id", None)
        if tenant_id is not None:
            return {"tenant_id": tenant_id}
        return None

    @staticmethod
    def _claim_mapper(request: Any) -> Any | None:
        app = getattr(request, "app", None)
        state = getattr(app, "state", None)
        return getattr(state, "oidc_claim_mapper", None)


__all__ = ["TenantResolver"]

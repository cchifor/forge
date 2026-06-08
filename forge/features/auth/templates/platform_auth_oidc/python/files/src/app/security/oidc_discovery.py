"""OIDC discovery — resolve an issuer's JWKS URI.

Given an issuer base URL, the OpenID Connect Discovery spec
(`openid-connect-discovery-1_0 §4 <https://openid.net/specs/openid-connect-discovery-1_0.html>`_)
publishes a provider-metadata document at
``<issuer>/.well-known/openid-configuration`` whose ``jwks_uri`` member
points at the signing-key set. This module fetches that document, extracts
``jwks_uri``, and caches the result for the process lifetime.

Robustness contract:

* If ``AUTH_PROVIDER_JWKS_URI`` is set, the caller skips discovery entirely
  and uses that value verbatim — no network call at boot.
* Otherwise we prefer discovery. On any discovery failure (network error,
  non-200, malformed JSON, missing ``jwks_uri``) we fall back to the
  conventional Keycloak path ``<issuer>/protocol/openid-connect/certs`` so a
  direct-Keycloak deployment still boots when its discovery endpoint is
  momentarily unreachable. The fallback is logged at WARNING so the operator
  notices a degraded resolution.

The fetch uses the SAME ``httpx.AsyncClient`` the JWKS cache uses, so the
in-memory ``MockTransport`` test seam works here too.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

_log = logging.getLogger(__name__)

DISCOVERY_SUFFIX = "/.well-known/openid-configuration"
# Keycloak's well-known JWKS path. Used ONLY as a discovery fallback; modern
# IdPs (Auth0, Cognito, Okta) all serve discovery, so this branch is the
# direct-Keycloak safety net.
KEYCLOAK_CERTS_SUFFIX = "/protocol/openid-connect/certs"

DEFAULT_DISCOVERY_TIMEOUT = 5.0


def discovery_url(issuer: str) -> str:
    """Return the OIDC discovery document URL for ``issuer``."""
    return f"{issuer.rstrip('/')}{DISCOVERY_SUFFIX}"


def keycloak_certs_fallback(issuer: str) -> str:
    """Return the conventional Keycloak JWKS URL for ``issuer``."""
    return f"{issuer.rstrip('/')}{KEYCLOAK_CERTS_SUFFIX}"


class OIDCDiscovery:
    """Cache-backed JWKS-URI resolver for a single issuer.

    Constructed once per process. The first :meth:`resolve_jwks_uri` call
    performs the discovery fetch (unless an explicit override is supplied);
    subsequent calls return the cached value without any network I/O.
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_DISCOVERY_TIMEOUT,
    ) -> None:
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._timeout = timeout
        self._cache: dict[str, str] = {}

    async def resolve_jwks_uri(self, issuer: str, *, override: str | None = None) -> str:
        """Resolve the JWKS URI for ``issuer``.

        Resolution order:

        1. ``override`` (``AUTH_PROVIDER_JWKS_URI``) — used verbatim, cached,
           no network call.
        2. Cached value from a previous resolution.
        3. OIDC discovery — fetch ``<issuer>/.well-known/openid-configuration``
           and read ``jwks_uri``.
        4. Fallback — ``<issuer>/protocol/openid-connect/certs`` (Keycloak
           convention) when discovery fails.
        """
        norm = issuer.rstrip("/")
        if override:
            self._cache[norm] = override
            return override
        if norm in self._cache:
            return self._cache[norm]

        try:
            jwks_uri = await self._fetch_jwks_uri(norm)
        except Exception as exc:  # noqa: BLE001 — degrade, don't crash boot.
            fallback = keycloak_certs_fallback(norm)
            _log.warning(
                "oidc_discovery_failed_using_fallback",
                extra={
                    "issuer": norm,
                    "discovery_url": discovery_url(norm),
                    "fallback": fallback,
                    "error": str(exc),
                },
            )
            self._cache[norm] = fallback
            return fallback

        self._cache[norm] = jwks_uri
        return jwks_uri

    async def _fetch_jwks_uri(self, issuer: str) -> str:
        url = discovery_url(issuer)
        resp = await self._http.get(url, timeout=self._timeout)
        resp.raise_for_status()
        doc: Any = resp.json()
        if not isinstance(doc, dict):
            raise ValueError("discovery document is not a JSON object")
        jwks_uri = doc.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise ValueError("discovery document missing 'jwks_uri'")
        # Defensive: some IdPs publish a discovery ``issuer`` that differs
        # from the configured base URL (trailing slash, scheme). We don't
        # reject on that here — the AuthGuard's registered-issuer + trust-map
        # checks are the authoritative ``iss`` comparison.
        return jwks_uri

    async def aclose(self) -> None:
        """Release the underlying HTTP client if this resolver owns it."""
        if self._owns_http:
            await self._http.aclose()


__all__ = [
    "DEFAULT_DISCOVERY_TIMEOUT",
    "DISCOVERY_SUFFIX",
    "KEYCLOAK_CERTS_SUFFIX",
    "OIDCDiscovery",
    "discovery_url",
    "keycloak_certs_fallback",
]

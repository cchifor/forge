"""In-process dev token issuer — zero external dependencies.

The ``in_memory`` auth provider replaces the Gatekeeper token authority with
a self-contained issuer that lives *inside* the service process: it mints
ES256 dev JWTs and serves the matching JWKS without ever touching a network,
a Keycloak realm, a Gatekeeper container, or Redis.

It is wired in two halves:

* :class:`InMemoryIssuer` owns an ECDSA P-256 (ES256) keypair — the same
  crypto the platform-auth SDK's ``TestKeypair`` uses — and can both
  ``mint(...)`` signed tokens and expose its ``jwks_document()``.
* :func:`build_in_memory_auth_bundle` builds an
  :class:`~service.security.platform_auth_setup.AuthGuardBundle` whose
  ``JWKSCache`` is pointed at this issuer's JWKS over an in-memory
  ``httpx.MockTransport`` (no real HTTP), and whose trust map trusts the
  issuer for the configured tenant. The resulting guard verifies the exact
  tokens this issuer mints.

This module is intended for **local development and tests only**. The
generated stack refuses ``auth.provider=in_memory`` under a production
posture (see forge's capability resolver / the service's own config guard).
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

import httpx
import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from platform_auth import (
    AllowAllMayActPolicy,
    AuthGuard,
    InMemoryIssuerTrustMap,
    JWKSCache,
    TenantTrust,
)

from weld.core.domain.config import AuthConfig
from service.security.platform_auth_setup import AuthGuardBundle

# Conventional URLs / identifiers for the in-process issuer. The issuer URL
# is a stable, non-routable ``urn:`` so it can never be confused with a real
# network endpoint, and the JWKS URI is a synthetic ``http://`` URL that only
# resolves through the in-memory MockTransport below.
DEV_ISSUER = "urn:forge:dev:in-memory-issuer"
DEV_JWKS_URI = "http://in-memory-issuer.local/dev/auth/jwks"
DEV_TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")

# Forge-namespaced claim names — must match the AuthGuard configuration so
# minted tokens verify cleanly. ``AuthConfig.tenant_id_claim`` defaults to
# the forge-namespaced URL; the issuer mirrors it.
DEFAULT_TENANT_ID_CLAIM = "https://forge/tenant_id"
DEFAULT_TENANT_SLUG_CLAIM = "https://forge/tenant_slug"


class InMemoryIssuer:
    """An in-process ES256 token issuer + JWKS provider.

    Generates a fresh ECDSA P-256 keypair at construction (sub-millisecond),
    mints RFC 9068-shaped access tokens, and exposes the public half as a
    JWKS document. No state is persisted: every process restart rotates the
    key, which is exactly what a throwaway dev issuer wants.
    """

    def __init__(
        self,
        *,
        issuer: str = DEV_ISSUER,
        audience: str,
        kid: str = "in-memory-dev-kid",
        tenant_id_claim: str = DEFAULT_TENANT_ID_CLAIM,
        tenant_slug_claim: str = DEFAULT_TENANT_SLUG_CLAIM,
    ) -> None:
        if not audience:
            raise ValueError("audience must be non-empty")
        self._issuer = issuer
        self._audience = audience
        self._kid = kid
        self._tenant_id_claim = tenant_id_claim
        self._tenant_slug_claim = tenant_slug_claim
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self._private_pem: bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @property
    def issuer(self) -> str:
        return self._issuer

    @property
    def audience(self) -> str:
        return self._audience

    @property
    def kid(self) -> str:
        return self._kid

    def public_jwk(self) -> dict[str, Any]:
        """Return the public-key half of the keypair as a JWK dict."""
        jwk_str = pyjwt.algorithms.ECAlgorithm.to_jwk(self._private_key.public_key())
        jwk: dict[str, Any] = json.loads(jwk_str)
        jwk["kid"] = self._kid
        jwk["alg"] = "ES256"
        jwk["use"] = "sig"
        return jwk

    def jwks_document(self) -> dict[str, Any]:
        """Return a complete JWKS document with this key as the only entry."""
        return {"keys": [self.public_jwk()]}

    def mint(
        self,
        *,
        sub: str,
        scopes: Iterable[str] | str = (),
        tenant_id: UUID | str = DEV_TENANT_ID,
        roles: Iterable[str] = (),
        exp_seconds: int = 3600,
        tenant_slug: str | None = None,
        extra_claims: Mapping[str, Any] | None = None,
    ) -> str:
        """Mint and sign a dev access token (ES256, RFC 9068 profile)."""
        now = int(time.time())
        scope_value = scopes if isinstance(scopes, str) else " ".join(scopes)
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": sub,
            "iat": now,
            "nbf": now,
            "exp": now + exp_seconds,
            "jti": str(uuid.uuid4()),
            self._tenant_id_claim: str(tenant_id),
            "scope": scope_value,
            "roles": list(roles),
        }
        if tenant_slug is not None:
            claims[self._tenant_slug_claim] = tenant_slug
        if extra_claims:
            claims.update(extra_claims)
        return pyjwt.encode(
            claims,
            self._private_pem,
            algorithm="ES256",
            headers={"kid": self._kid},
        )


def _make_jwks_cache(issuer: InMemoryIssuer) -> JWKSCache:
    """Build a JWKSCache that resolves the issuer's JWKS in-process.

    Uses ``httpx.MockTransport`` so ``JWKSCache._fetch`` succeeds without any
    real network call — the same short-circuit the SDK's test fixtures use.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=issuer.jwks_document())

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = JWKSCache(http_client=http)
    cache.register_issuer(issuer.issuer, DEV_JWKS_URI)
    return cache


def build_in_memory_auth_bundle(
    config: AuthConfig,
    issuer: InMemoryIssuer,
) -> AuthGuardBundle:
    """The ``in_memory`` variant of ``build_auth_guard``.

    Wires an :class:`AuthGuard` against ``issuer``'s own in-process JWKS
    instead of the Gatekeeper's. Tenant trust is permissive for the single
    dev tenant; the may-act policy is ``AllowAll`` (delegation chains are not
    a dev concern). Algorithms are locked to ES256, matching the issuer.
    """
    jwks = _make_jwks_cache(issuer)

    trust = InMemoryIssuerTrustMap()
    trust.set(DEV_TENANT_ID, TenantTrust(expected_issuer=issuer.issuer, suspended=False))

    guard = AuthGuard(
        audience=issuer.audience,
        jwks=jwks,
        trust_map=trust,
        may_act=AllowAllMayActPolicy(),
        algorithms=("ES256",),
        tenant_id_claim=config.tenant_id_claim,
    )
    return AuthGuardBundle(guard=guard, jwks=jwks, trust_map=trust, may_act=AllowAllMayActPolicy())

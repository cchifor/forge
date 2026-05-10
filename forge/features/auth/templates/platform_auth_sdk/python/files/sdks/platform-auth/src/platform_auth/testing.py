"""Public test fixtures and helpers for platform-auth.

This module is consumed by every service's test suite to mint signed JWTs
and wire :class:`platform_auth.AuthGuard` against an in-memory JWKS server.
It is the canonical replacement for the ad-hoc ``X-Gatekeeper-Tenant``
header fixtures the codebase currently uses.

Quick start in a service's test::

    from platform_auth.testing import TestAuthEnvironment, build_test_token

    async def test_authorized_request(auth_env: TestAuthEnvironment):
        token = auth_env.token(scopes="workflow:read")
        response = await client.get("/workflows", headers=auth_env.bearer(token))
        assert response.status_code == 200

The ``auth_env`` fixture comes from this module; importing ``platform_auth.testing``
anywhere in your conftest is enough to register it.

Note: this module imports ``pytest``. That is intentional — the module
exists for tests, never imported in production code paths.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from platform_auth.auth_guard import (
    DEFAULT_TENANT_ID_CLAIM,
    DEFAULT_TENANT_SLUG_CLAIM,
    AuthGuard,
)
from platform_auth.jwks import JWKSCache
from platform_auth.may_act import AllowAllMayActPolicy
from platform_auth.trust import (
    InMemoryIssuerTrustMap,
    IssuerTrustMap,
    TenantTrust,
)

DEFAULT_TEST_ISSUER = "https://idp.test/realms/platform"
DEFAULT_TEST_AUDIENCE = "svc-test"
DEFAULT_TEST_TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


class TestKeypair:
    """ECDSA P-256 keypair that signs test JWTs and exposes the matching
    JWKS document.

    Phase 4 default. The platform standardised on ES256 — gatekeeper-
    minted internal JWTs are ECDSA P-256 — so test fixtures match.
    Generation is sub-millisecond, far cheaper than the previous RSA
    keypair (~50–100 ms), so a per-test-function scope is now affordable.

    Tests that genuinely need RS256 (e.g. Keycloak-token integration
    fixtures) instantiate :class:`TestRSAKeypair` and pass
    ``algorithms=("RS256",)`` to AuthGuard explicitly.
    """

    # Tell pytest this class isn't a test container — it's a value object
    # that happens to start with "Test".
    __test__ = False

    def __init__(self, *, kid: str = "test-kid") -> None:
        self._kid = kid
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self._private_pem: bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

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

    def sign(self, claims: Mapping[str, Any]) -> str:
        """Sign ``claims`` with this keypair using ES256."""
        return pyjwt.encode(
            dict(claims),
            self._private_pem,
            algorithm="ES256",
            headers={"kid": self._kid},
        )


class TestRSAKeypair:
    """Legacy RSA keypair for tests that explicitly need RS256.

    Used by integration tests that mimic Keycloak's RSA-signed access
    tokens. Production callers default to :class:`TestKeypair` (ES256).
    """

    __test__ = False

    def __init__(self, *, kid: str = "test-kid-rsa", key_size: int = 2048) -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa as _rsa

        self._kid = kid
        self._private_key = _rsa.generate_private_key(
            public_exponent=65537, key_size=key_size
        )
        self._private_pem: bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @property
    def kid(self) -> str:
        return self._kid

    def public_jwk(self) -> dict[str, Any]:
        jwk_str = pyjwt.algorithms.RSAAlgorithm.to_jwk(self._private_key.public_key())
        jwk: dict[str, Any] = json.loads(jwk_str)
        jwk["kid"] = self._kid
        jwk["alg"] = "RS256"
        jwk["use"] = "sig"
        return jwk

    def jwks_document(self) -> dict[str, Any]:
        return {"keys": [self.public_jwk()]}

    def sign(self, claims: Mapping[str, Any]) -> str:
        return pyjwt.encode(
            dict(claims),
            self._private_pem,
            algorithm="RS256",
            headers={"kid": self._kid},
        )


def make_jwks_transport(keypair: TestKeypair) -> httpx.MockTransport:
    """Build an :class:`httpx.MockTransport` that responds with ``keypair``'s JWKS.

    Use this transport with :class:`httpx.AsyncClient` and pass that client
    to :class:`platform_auth.JWKSCache` to short-circuit the network.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=keypair.jwks_document())

    return httpx.MockTransport(handler)


def make_jwks_cache(
    keypair: TestKeypair,
    *,
    issuer: str = DEFAULT_TEST_ISSUER,
    jwks_uri: str | None = None,
) -> JWKSCache:
    """Build a :class:`JWKSCache` wired to a fake JWKS server backed by ``keypair``.

    Caller owns the returned cache and must ``await cache.aclose()`` when
    done. The fixtures in this module take care of that automatically.
    """
    jwks_uri = jwks_uri or f"{issuer}/protocol/openid-connect/certs"
    http = httpx.AsyncClient(transport=make_jwks_transport(keypair))
    cache = JWKSCache(http_client=http)
    cache.register_issuer(issuer, jwks_uri)
    return cache


def build_test_token(
    *,
    keypair: TestKeypair,
    audience: str = DEFAULT_TEST_AUDIENCE,
    issuer: str = DEFAULT_TEST_ISSUER,
    tenant_id: UUID | str = DEFAULT_TEST_TENANT_ID,
    subject: str = "test-user-1",
    scopes: Iterable[str] | str = (),
    roles: Iterable[str] = (),
    exp_seconds: int = 900,
    nbf_offset_seconds: int = 0,
    iat_offset_seconds: int = 0,
    jti: str | None = None,
    act: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    tenant_id_claim: str = DEFAULT_TENANT_ID_CLAIM,
    tenant_slug: str | None = None,
    tenant_slug_claim: str = DEFAULT_TENANT_SLUG_CLAIM,
    roles_claim: str = "roles",
    scope_claim: str = "scope",
    extra_claims: Mapping[str, Any] | None = None,
) -> str:
    """Build and sign a JWT shaped per the platform's RFC 9068 profile.

    Defaults produce a valid first-party token for the test tenant. Override
    individual arguments to construct rejection-path scenarios — e.g.
    ``exp_seconds=-60`` for an expired token, ``nbf_offset_seconds=300`` for
    a not-yet-valid token, ``audience="wrong-svc"`` for an audience mismatch.

    ``act`` may be a single dict (one-hop impersonation) or a list of dicts
    (chain ordered outermost-first) and is converted into the nested
    ``act`` shape expected by RFC 8693.

    ``roles_claim`` and ``scope_claim`` mirror the matching parameters on
    Node ``BuildTestTokenOptions.rolesClaim`` / ``scopeClaim`` and Rust
    ``BuildTestTokenOptions.roles_claim`` / ``scope_claim`` — overriding
    them lets parity scenarios exercise verifiers configured with custom
    claim names. Defaults match the cross-SDK ``"roles"`` / ``"scope"``
    convention.
    """
    now = int(time.time())
    scope_value = scopes if isinstance(scopes, str) else " ".join(scopes)
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": now + iat_offset_seconds,
        "nbf": now + nbf_offset_seconds,
        "exp": now + exp_seconds,
        "jti": jti or str(uuid.uuid4()),
        tenant_id_claim: str(tenant_id),
        scope_claim: scope_value,
        roles_claim: list(roles),
    }
    if tenant_slug is not None:
        claims[tenant_slug_claim] = tenant_slug
    if act is not None:
        claims["act"] = _build_act_chain(act)
    if extra_claims:
        claims.update(extra_claims)
    return keypair.sign(claims)


def _build_act_chain(
    act: Mapping[str, Any] | list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the nested ``act`` shape from a chain.

    A list ``[A, B, C]`` describes the chain "C acted as B acted as A".
    Outermost (most recent) actor is the first element; innermost is the
    last. The result is a single dict with nested ``act`` keys for each
    further hop.
    """
    if isinstance(act, Mapping):
        return dict(act)
    if not act:
        raise ValueError("act chain cannot be empty")
    result: dict[str, Any] = dict(act[-1])
    for entry in reversed(act[:-1]):
        result = {**entry, "act": result}
    return result


def bearer_headers(token: str) -> dict[str, str]:
    """Return ``{"Authorization": "Bearer <token>"}`` — the canonical
    replacement for ``{"X-Gatekeeper-Tenant": ...}`` fixtures."""
    return {"Authorization": f"Bearer {token}"}


@dataclass
class TestAuthEnvironment:
    """Bundle of test-time auth state.

    Tests typically receive one of these via the ``auth_env`` fixture and
    use it to mint tokens, build authenticated clients, and tear down
    cleanly.
    """

    # Tell pytest this dataclass isn't a test container.
    __test__ = False

    keypair: TestKeypair
    issuer: str
    audience: str
    jwks_cache: JWKSCache
    trust_map: InMemoryIssuerTrustMap
    auth_guard: AuthGuard

    def token(self, **overrides: Any) -> str:
        """Build a signed JWT with sensible defaults; override fields as needed."""
        kwargs = dict(
            keypair=self.keypair,
            issuer=self.issuer,
            audience=self.audience,
        )
        kwargs.update(overrides)
        return build_test_token(**kwargs)  # type: ignore[arg-type]

    def headers(self, **overrides: Any) -> dict[str, str]:
        """Build a signed JWT and wrap it in a Bearer header dict."""
        return bearer_headers(self.token(**overrides))

    def bearer(self, token: str) -> dict[str, str]:
        """Wrap an already-built token in a Bearer header dict."""
        return bearer_headers(token)

    def register_tenant(
        self,
        tenant_id: UUID = DEFAULT_TEST_TENANT_ID,
        *,
        suspended: bool = False,
        issuer: str | None = None,
    ) -> None:
        """Register a tenant in the in-memory trust map."""
        self.trust_map.set(
            tenant_id,
            TenantTrust(
                expected_issuer=issuer or self.issuer,
                suspended=suspended,
            ),
        )

    async def aclose(self) -> None:
        await self.jwks_cache.aclose()


@pytest.fixture
def test_keypair() -> TestKeypair:
    """Module-scoped RSA keypair would be faster but pytest's default
    scope keeps tests fully isolated. Override with ``scope="session"``
    in your conftest if you need the speed."""
    return TestKeypair()


@pytest.fixture
def issuer_trust_map() -> InMemoryIssuerTrustMap:
    """In-memory trust map pre-populated with the default test tenant."""
    trust = InMemoryIssuerTrustMap()
    trust.set(
        DEFAULT_TEST_TENANT_ID,
        TenantTrust(expected_issuer=DEFAULT_TEST_ISSUER, suspended=False),
    )
    return trust


@pytest.fixture
async def auth_env(
    test_keypair: TestKeypair,
    issuer_trust_map: InMemoryIssuerTrustMap,
) -> AsyncIterator[TestAuthEnvironment]:
    """End-to-end auth environment for service tests.

    Wires a JWKSCache against an in-memory JWKS server backed by
    ``test_keypair``, creates an AuthGuard targeting ``DEFAULT_TEST_AUDIENCE``,
    and yields a :class:`TestAuthEnvironment` covering common operations.
    Tear down is automatic.
    """
    jwks = make_jwks_cache(test_keypair, issuer=DEFAULT_TEST_ISSUER)
    guard = AuthGuard(
        audience=DEFAULT_TEST_AUDIENCE,
        jwks=jwks,
        trust_map=issuer_trust_map,
        # Tests opt into may_act via overrides; default permissive so the
        # majority case (no act chain) just works.
        may_act=AllowAllMayActPolicy(),
    )
    env = TestAuthEnvironment(
        keypair=test_keypair,
        issuer=DEFAULT_TEST_ISSUER,
        audience=DEFAULT_TEST_AUDIENCE,
        jwks_cache=jwks,
        trust_map=issuer_trust_map,
        auth_guard=guard,
    )
    try:
        yield env
    finally:
        await env.aclose()


__all__ = [
    "DEFAULT_TEST_AUDIENCE",
    "DEFAULT_TEST_ISSUER",
    "DEFAULT_TEST_TENANT_ID",
    "TestAuthEnvironment",
    "TestKeypair",
    "auth_env",
    "bearer_headers",
    "build_test_token",
    "issuer_trust_map",
    "make_jwks_cache",
    "make_jwks_transport",
    "test_keypair",
]


# A trust-map argument is accepted by AuthGuard via the IssuerTrustMap
# Protocol; this assignment ensures `IssuerTrustMap` remains exported even
# if the typing module trims unused imports during refactors.
_ = IssuerTrustMap  # pragma: no cover — keep import live for type-narrowing

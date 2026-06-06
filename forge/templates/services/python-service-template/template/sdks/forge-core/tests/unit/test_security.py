"""Contract + behaviour tests for ``forge_core.security``.

Covers the always-shipped, weld-free auth glue end to end:

* the registry-free scope hierarchy (:func:`scope_satisfies`),
* the new generic OIDC ``AuthConfig`` fields the security layer reads,
* the :class:`AuthGuard` JWT/JWKS verifier (happy path, expired, bad audience,
  bad issuer, forbidden algorithm, tenant-trust enforcement),
* the FastAPI request lifecycle (``authenticate_request`` passthrough when auth
  is disabled, dev-user synthesis, 401 on a bad token, identity → ``User``
  translation), and
* the always-on ``build_auth_guard`` bundle factory.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from forge_core.domain.config import AuthConfig
from forge_core.security import (
    AuthError,
    AuthGuard,
    AuthGuardBundle,
    IdentityContext,
    InMemoryIssuerTrustMap,
    InvalidToken,
    IssuerNotTrusted,
    JWKSCache,
    TenantSuspended,
    TenantTrust,
    TokenExpired,
    auth,
    build_auth_guard,
    issuer_url,
    jwks_uri,
    scope_satisfies,
)

ISSUER = "https://issuer.example/realms/forge"
AUDIENCE = "service-api"
TENANT_ID = "11111111-1111-1111-1111-111111111111"
TENANT_CLAIM = "https://forge/tenant_id"


# --------------------------------------------------------------------------- #
# Test keypair + JWKS-over-MockTransport helpers
# --------------------------------------------------------------------------- #
class _Keypair:
    """An ES256 (default) or RS256 signing keypair + matching JWKS document."""

    def __init__(self, *, alg: str = "ES256", kid: str = "test-kid") -> None:
        self.alg = alg
        self.kid = kid
        if alg == "ES256":
            self._key = ec.generate_private_key(ec.SECP256R1())
        else:
            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._pem: bytes = self._key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def public_jwk(self) -> dict[str, Any]:
        if self.alg == "ES256":
            jwk = json.loads(pyjwt.algorithms.ECAlgorithm.to_jwk(self._key.public_key()))
        else:
            jwk = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk["kid"] = self.kid
        jwk["alg"] = self.alg
        jwk["use"] = "sig"
        return jwk

    def jwks_document(self) -> dict[str, Any]:
        return {"keys": [self.public_jwk()]}

    def mint(
        self,
        *,
        sub: str = "user-1",
        aud: str = AUDIENCE,
        iss: str = ISSUER,
        exp_offset: int = 3600,
        tenant_id: str | None = TENANT_ID,
        tenant_claim: str = TENANT_CLAIM,
        scopes: str = "orders:read items:read",
        roles: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": iss,
            "aud": aud,
            "sub": sub,
            "iat": now,
            "nbf": now,
            "exp": now + exp_offset,
            "jti": "jti-1",
            "scope": scopes,
            "roles": roles if roles is not None else ["user"],
        }
        if tenant_id is not None:
            claims[tenant_claim] = tenant_id
        if extra:
            claims.update(extra)
        return pyjwt.encode(claims, self._pem, algorithm=self.alg, headers={"kid": self.kid})


def _jwks_cache(keypair: _Keypair, *, issuer: str = ISSUER) -> JWKSCache:
    """A JWKSCache that resolves ``keypair``'s JWKS over an in-memory transport."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=keypair.jwks_document())

    cache = JWKSCache(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    cache.register_issuer(issuer, f"{issuer}/protocol/openid-connect/certs")
    return cache


def _guard(keypair: _Keypair, *, algorithms: tuple[str, ...] = ("ES256",), **kw: Any) -> AuthGuard:
    return AuthGuard(
        audience=AUDIENCE,
        jwks=_jwks_cache(keypair),
        algorithms=algorithms,
        tenant_id_claim=TENANT_CLAIM,
        **kw,
    )


# --------------------------------------------------------------------------- #
# scope_satisfies — registry-free hierarchy
# --------------------------------------------------------------------------- #
class TestScopeSatisfies:
    def test_empty_required_is_a_noop_gate(self) -> None:
        assert scope_satisfies("", []) is True

    def test_exact_match(self) -> None:
        assert scope_satisfies("orders:read", {"orders:read"}) is True

    def test_empty_held_denies_non_empty_required(self) -> None:
        assert scope_satisfies("orders:read", []) is False

    def test_super_wildcard_covers_everything(self) -> None:
        assert scope_satisfies("anything:at:all", {"*"}) is True

    def test_verb_wildcard(self) -> None:
        assert scope_satisfies("orders:read", {"orders:*"}) is True
        # but not deeper
        assert scope_satisfies("orders:admin:retry", {"orders:*"}) is False

    def test_namespace_wildcard(self) -> None:
        assert scope_satisfies("orders:read", {"*:read"}) is True

    def test_no_hardcoded_service_enum(self) -> None:
        # A project-defined namespace forge never heard of resolves identically.
        assert scope_satisfies("widgets:write", {"widgets:*"}) is True


# --------------------------------------------------------------------------- #
# AuthConfig — generic OIDC fields the security layer reads
# --------------------------------------------------------------------------- #
class TestAuthConfigSecurityFields:
    def test_default_jwks_uri_derives_certs_url(self) -> None:
        cfg = AuthConfig(server_url="http://localhost:8080", realm="forge", client_id="svc")
        assert cfg.default_jwks_uri == (
            "http://localhost:8080/realms/forge/protocol/openid-connect/certs"
        )

    def test_explicit_jwks_uri_overrides(self) -> None:
        cfg = AuthConfig(
            server_url="http://localhost:8080",
            client_id="svc",
            jwks_uri="https://idp.example/keys/",
        )
        assert cfg.default_jwks_uri == "https://idp.example/keys"

    def test_claim_name_defaults_are_generic(self) -> None:
        cfg = AuthConfig(server_url="http://localhost:8080", client_id="svc")
        assert cfg.tenant_id_claim == "https://forge/tenant_id"
        assert cfg.tenant_slug_claim == "https://forge/tenant_slug"


# --------------------------------------------------------------------------- #
# build_auth_guard — the always-shipped bundle factory
# --------------------------------------------------------------------------- #
class TestBuildAuthGuard:
    def test_builds_a_bundle_registered_for_the_configured_issuer(self) -> None:
        cfg = AuthConfig(
            server_url="http://localhost:8080", realm="forge", client_id="svc", audience="svc-api"
        )
        bundle = build_auth_guard(cfg)
        assert isinstance(bundle, AuthGuardBundle)
        assert bundle.guard.audience == "svc-api"
        assert issuer_url(cfg) in bundle.jwks.registered_issuers()

    def test_jwks_uri_honours_override(self) -> None:
        cfg = AuthConfig(
            server_url="http://localhost:8080", client_id="svc", jwks_uri="https://idp/keys"
        )
        assert jwks_uri(cfg) == "https://idp/keys"


# --------------------------------------------------------------------------- #
# AuthGuard — JWT/JWKS verification
# --------------------------------------------------------------------------- #
class TestAuthGuardVerify:
    async def test_happy_path_es256(self) -> None:
        kp = _Keypair(alg="ES256")
        identity = await _guard(kp).verify(kp.mint())
        assert isinstance(identity, IdentityContext)
        assert identity.tenant_id == TENANT_ID
        assert identity.subject == "user-1"
        assert identity.has_scope("orders:read")
        assert "user" in identity.roles

    async def test_happy_path_rs256_when_configured(self) -> None:
        kp = _Keypair(alg="RS256")
        identity = await _guard(kp, algorithms=("RS256",)).verify(kp.mint())
        assert identity.subject == "user-1"

    async def test_expired_token_raises_token_expired(self) -> None:
        # Well past the default 30s clock-skew leeway.
        kp = _Keypair()
        with pytest.raises(TokenExpired):
            await _guard(kp).verify(kp.mint(exp_offset=-120))

    async def test_roles_as_space_separated_string(self) -> None:
        kp = _Keypair()
        identity = await _guard(kp).verify(kp.mint(extra={"roles": "admin, user editor"}))
        assert identity.roles == frozenset({"admin", "user", "editor"})

    async def test_scopes_as_list(self) -> None:
        kp = _Keypair()
        identity = await _guard(kp).verify(kp.mint(extra={"scope": ["a:read", "b:write"]}))
        assert identity.has_all_scopes("a:read", "b:write")

    async def test_malformed_header_raises_invalid_token(self) -> None:
        kp = _Keypair()
        with pytest.raises(InvalidToken):
            await _guard(kp).verify("a.b")

    async def test_bad_audience_raises_invalid_token(self) -> None:
        kp = _Keypair()
        with pytest.raises(InvalidToken):
            await _guard(kp).verify(kp.mint(aud="someone-else"))

    async def test_unregistered_issuer_raises_invalid_token(self) -> None:
        kp = _Keypair()
        with pytest.raises(InvalidToken):
            await _guard(kp).verify(kp.mint(iss="https://evil.example"))

    async def test_forbidden_algorithm_rejected(self) -> None:
        # Token signed with RS256, guard only accepts ES256.
        kp = _Keypair(alg="RS256")
        guard = AuthGuard(
            audience=AUDIENCE,
            jwks=_jwks_cache(kp),
            algorithms=("ES256",),
            tenant_id_claim=TENANT_CLAIM,
        )
        with pytest.raises(InvalidToken):
            await guard.verify(kp.mint())

    async def test_alg_none_is_rejected_at_construction(self) -> None:
        kp = _Keypair()
        with pytest.raises(ValueError):
            AuthGuard(audience=AUDIENCE, jwks=_jwks_cache(kp), algorithms=("none",))

    async def test_missing_tenant_claim_raises(self) -> None:
        kp = _Keypair()
        with pytest.raises(InvalidToken):
            await _guard(kp).verify(kp.mint(tenant_id=None))

    async def test_empty_token_raises(self) -> None:
        kp = _Keypair()
        with pytest.raises(InvalidToken):
            await _guard(kp).verify("")


class TestAuthGuardTrustMap:
    async def test_matching_issuer_passes(self) -> None:
        kp = _Keypair()
        trust = InMemoryIssuerTrustMap()
        trust.set(TENANT_ID, TenantTrust(expected_issuer=ISSUER))
        guard = _guard(kp, trust_map=trust)
        identity = await guard.verify(kp.mint())
        assert identity.tenant_id == TENANT_ID

    async def test_mismatched_issuer_rejected(self) -> None:
        kp = _Keypair()
        trust = InMemoryIssuerTrustMap()
        trust.set(TENANT_ID, TenantTrust(expected_issuer="https://other.example"))
        with pytest.raises(IssuerNotTrusted):
            await _guard(kp, trust_map=trust).verify(kp.mint())

    async def test_suspended_tenant_rejected(self) -> None:
        kp = _Keypair()
        trust = InMemoryIssuerTrustMap()
        trust.set(TENANT_ID, TenantTrust(expected_issuer=ISSUER, suspended=True))
        with pytest.raises(TenantSuspended):
            await _guard(kp, trust_map=trust).verify(kp.mint())

    async def test_empty_trust_map_is_permissive(self) -> None:
        # No record for the tenant → single-issuer default accepts it.
        kp = _Keypair()
        identity = await _guard(kp, trust_map=InMemoryIssuerTrustMap()).verify(kp.mint())
        assert identity.tenant_id == TENANT_ID


# --------------------------------------------------------------------------- #
# JWKSCache — fetch, rotation, staleness, validation
# --------------------------------------------------------------------------- #
class TestJWKSCache:
    def test_rejects_bad_lifespans(self) -> None:
        with pytest.raises(ValueError):
            JWKSCache(lifespan_seconds=0)
        with pytest.raises(ValueError):
            JWKSCache(lifespan_seconds=600, stale_max_seconds=100)

    def test_register_issuer_validates(self) -> None:
        cache = JWKSCache()
        with pytest.raises(ValueError):
            cache.register_issuer("", "https://x/keys")
        with pytest.raises(ValueError):
            cache.register_issuer("iss", "")

    def test_register_issuer_is_idempotent_and_replaceable(self) -> None:
        cache = JWKSCache()
        cache.register_issuer("iss", "https://x/keys")
        cache.register_issuer("iss", "https://x/keys")  # no-op
        cache.register_issuer("iss", "https://y/keys")  # replace
        assert cache.registered_issuers() == frozenset({"iss"})

    async def test_unregistered_issuer_lookup_raises_keyerror(self) -> None:
        cache = JWKSCache()
        with pytest.raises(KeyError):
            await cache.get_signing_key("nope", "kid")

    async def test_unknown_kid_after_refresh_raises_invalid_token(self) -> None:
        kp = _Keypair()
        cache = _jwks_cache(kp)
        with pytest.raises(InvalidToken):
            await cache.get_signing_key(ISSUER, "no-such-kid")

    async def test_non_signing_keys_are_skipped(self) -> None:
        kp = _Keypair()

        def handler(_req: httpx.Request) -> httpx.Response:
            doc = kp.jwks_document()
            doc["keys"].insert(0, {"kid": "enc-key", "use": "enc", "kty": "RSA"})
            return httpx.Response(200, json=doc)

        cache = JWKSCache(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        cache.register_issuer(ISSUER, f"{ISSUER}/certs")
        jwk = await cache.get_signing_key(ISSUER, kp.kid)
        assert jwk is not None

    async def test_empty_jwks_raises(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"keys": []})

        cache = JWKSCache(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        cache.register_issuer(ISSUER, f"{ISSUER}/certs")
        with pytest.raises(InvalidToken):
            await cache.get_signing_key(ISSUER, "kid")

    async def test_aclose_is_safe(self) -> None:
        cache = JWKSCache()
        await cache.aclose()


# --------------------------------------------------------------------------- #
# IdentityContext / trust / exceptions surface
# --------------------------------------------------------------------------- #
class TestIdentitySurface:
    def test_scope_helpers(self) -> None:
        idc = IdentityContext(tenant_id="t", subject="s", scopes=frozenset({"orders:read"}))
        assert idc.has_any_scope("orders:read", "x:y") is True
        assert idc.has_all_scopes("orders:read", "x:y") is False
        assert idc.is_actor is False

    def test_actor_flag(self) -> None:
        idc = IdentityContext(tenant_id="t", subject="s", actor="svc-x")
        assert idc.is_actor is True

    def test_trust_map_remove(self) -> None:
        trust = InMemoryIssuerTrustMap()
        trust.set("t", TenantTrust(expected_issuer=ISSUER))
        trust.remove("t")
        trust.remove("t")  # no-op
        assert trust._records == {}  # type: ignore[attr-defined]

    def test_scope_required_carries_missing(self) -> None:
        from forge_core.security import ScopeRequired

        err = ScopeRequired(missing_scopes=frozenset({"orders:admin"}))
        assert err.status_code == 403
        assert "orders:admin" in err.missing_scopes


# --------------------------------------------------------------------------- #
# auth.py — FastAPI request lifecycle
# --------------------------------------------------------------------------- #
class _FakeState:
    pass


class _FakeApp:
    def __init__(self) -> None:
        self.state = _FakeState()


class _FakeRequest:
    """Minimal duck-typed Request for the auth module (headers + state + app)."""

    def __init__(self, app: _FakeApp, *, token: str | None = None) -> None:
        self.app = app
        self.state = _FakeState()
        self.headers = httpx.Headers({"Authorization": f"Bearer {token}"} if token else {})


def _init_app(*, dev_mode: bool, keypair: _Keypair | None = None) -> _FakeApp:
    app = _FakeApp()
    kp = keypair or _Keypair()
    bundle = AuthGuardBundle(
        guard=_guard(kp),
        jwks=_jwks_cache(kp),
        trust_map=InMemoryIssuerTrustMap(),
    )
    auth.initialize_auth(
        app,  # type: ignore[arg-type]
        bundle=bundle,
        auth_url="http://idp/auth",
        token_url="http://idp/token",
        dev_mode=dev_mode,
    )
    return app


class TestAuthenticateRequest:
    async def test_dev_mode_passthrough_synthesizes_dev_user(self) -> None:
        app = _init_app(dev_mode=True)
        req = _FakeRequest(app, token=None)
        user = await auth.authenticate_request(req)  # type: ignore[arg-type]
        assert user is not None
        assert user.username == "dev-user"
        # The synthesized identity is also bound for tenant-aware consumers.
        assert req.state.identity.tenant_id  # type: ignore[attr-defined]

    async def test_no_token_no_dev_mode_returns_none(self) -> None:
        app = _init_app(dev_mode=False)
        req = _FakeRequest(app, token=None)
        assert await auth.authenticate_request(req) is None  # type: ignore[arg-type]

    async def test_valid_token_translates_to_user(self) -> None:
        kp = _Keypair()
        app = _FakeApp()
        bundle = AuthGuardBundle(
            guard=_guard(kp), jwks=_jwks_cache(kp), trust_map=InMemoryIssuerTrustMap()
        )
        auth.initialize_auth(
            app,  # type: ignore[arg-type]
            bundle=bundle,
            auth_url="http://idp/auth",
            token_url="http://idp/token",
            dev_mode=False,
        )
        req = _FakeRequest(app, token=kp.mint(extra={"preferred_username": "alice"}))
        user = await auth.authenticate_request(req)  # type: ignore[arg-type]
        assert user is not None
        assert user.username == "alice"
        assert user.customer_id == TENANT_ID

    async def test_bad_token_raises_http_401(self) -> None:
        from fastapi import HTTPException

        app = _init_app(dev_mode=False)
        req = _FakeRequest(app, token="not-a-jwt")
        with pytest.raises(HTTPException) as exc:
            await auth.authenticate_request(req)  # type: ignore[arg-type]
        assert exc.value.status_code == 401

    async def test_uninitialized_app_raises_runtime_error(self) -> None:
        req = _FakeRequest(_FakeApp(), token=None)
        with pytest.raises(RuntimeError, match="Auth not initialized"):
            await auth.authenticate_request(req)  # type: ignore[arg-type]


def _make_user():
    from forge_core.domain.user import User

    return User(
        id="u1",
        username="alice",
        email="a@x",
        first_name="A",
        last_name="L",
        roles=["user"],
        customer_id="t1",
        token={},
    )


class TestFastAPIDependencies:
    async def test_get_current_user_returns_user(self) -> None:
        from forge_core.domain import context

        user = _make_user()
        await auth.set_auth_context(user)
        assert context.get_customer_id() == user.customer_id
        got = await auth.get_current_user(user, None)
        assert got is user

    async def test_get_current_user_raises_when_anonymous(self) -> None:
        from fastapi import HTTPException

        await auth.set_auth_context(None)  # binds public/anonymous
        with pytest.raises(HTTPException):
            await auth.get_current_user(None, None)

    async def test_get_optional_user_passthrough(self) -> None:
        assert await auth.get_optional_user(None, None) is None


class TestUserFromIdentity:
    def test_maps_claims_and_flags_service_accounts(self) -> None:
        identity = IdentityContext(
            tenant_id=TENANT_ID,
            subject="svc-sub",
            roles=frozenset({"reader"}),
            scopes=frozenset({"orders:read"}),
            raw_claims={
                "email": "svc@example.com",
                "azp": "svc-orders",
                "given_name": "Order",
                "family_name": "Service",
            },
        )
        user = auth.user_from_identity(identity, httpx.Headers())
        assert user.email == "svc@example.com"
        assert user.service_account is True
        assert user.first_name == "Order"


class TestAuthErrorContract:
    def test_auth_error_carries_reason_and_status(self) -> None:
        err = InvalidToken("nope")
        assert isinstance(err, AuthError)
        assert err.reason == "invalid_token"
        assert err.status_code == 401

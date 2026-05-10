"""AuthGuard end-to-end verification tests.

These tests exercise the full token-validation pipeline against a fake
JWKS server and an in-memory trust map. They are the contract tests for
every rejection path the plan calls out.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from platform_auth.auth_guard import AuthGuard
from platform_auth.exceptions import (
    ActorNotAuthorized,
    InvalidToken,
    IssuerNotTrusted,
    TenantSuspended,
    TokenExpired,
    TokenRevoked,
)
from platform_auth.may_act import StaticMayActPolicy
from platform_auth.revocation import RevocationStore
from platform_auth.testing import (
    DEFAULT_TEST_AUDIENCE,
    DEFAULT_TEST_ISSUER,
    DEFAULT_TEST_TENANT_ID,
    TestAuthEnvironment,
    bearer_headers,
    build_test_token,
    make_jwks_cache,
)


def _request(headers: dict[str, str]) -> Any:
    """Build a minimal request stub matching what FastAPI delivers."""
    return SimpleNamespace(headers=headers, state=SimpleNamespace())


# --------------------------------------------------------------- happy paths


class TestHappyPath:
    async def test_valid_token_returns_identity(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(scopes="workflow:read profile:read")
        identity = await auth_env.auth_guard.verify(token)
        assert identity.tenant_id == DEFAULT_TEST_TENANT_ID
        assert identity.subject == "test-user-1"
        assert identity.scopes == frozenset({"workflow:read", "profile:read"})
        assert identity.actor is None
        assert not identity.is_actor

    async def test_call_dunder_extracts_bearer_and_sets_state(self, auth_env: TestAuthEnvironment):
        token = auth_env.token()
        request = _request(bearer_headers(token))
        identity = await auth_env.auth_guard(request)
        assert identity.subject == "test-user-1"
        assert request.state.identity is identity

    async def test_lowercase_authorization_header_accepted(self, auth_env: TestAuthEnvironment):
        token = auth_env.token()
        request = _request({"authorization": f"Bearer {token}"})
        identity = await auth_env.auth_guard(request)
        assert identity.subject == "test-user-1"

    async def test_roles_list_parsed(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(roles=["editor", "viewer"])
        identity = await auth_env.auth_guard.verify(token)
        assert identity.roles == frozenset({"editor", "viewer"})

    async def test_scopes_as_list_parsed(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(scopes=["workflow:read", "profile:read"])
        identity = await auth_env.auth_guard.verify(token)
        assert identity.scopes == frozenset({"workflow:read", "profile:read"})

    async def test_no_scopes_yields_empty_frozenset(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(scopes="")
        identity = await auth_env.auth_guard.verify(token)
        assert identity.scopes == frozenset()


# ----------------------------------------------------- bearer-extraction errors


class TestBearerExtraction:
    async def test_missing_authorization_header(self, auth_env: TestAuthEnvironment):
        with pytest.raises(InvalidToken, match="missing Authorization header"):
            await auth_env.auth_guard(_request({}))

    async def test_non_bearer_scheme(self, auth_env: TestAuthEnvironment):
        with pytest.raises(InvalidToken, match="not a Bearer token"):
            await auth_env.auth_guard(_request({"Authorization": "Basic xxx"}))

    async def test_empty_bearer(self, auth_env: TestAuthEnvironment):
        with pytest.raises(InvalidToken, match="not a Bearer token"):
            await auth_env.auth_guard(_request({"Authorization": "Bearer "}))


# ------------------------------------------------------------- header errors


class TestTokenHeader:
    async def test_malformed_token(self, auth_env: TestAuthEnvironment):
        with pytest.raises(InvalidToken, match="malformed token"):
            await auth_env.auth_guard.verify("not-a-jwt")

    async def test_alg_none_rejected(self, auth_env: TestAuthEnvironment):
        # Manually craft a header.payload.signature with alg=none.
        import base64
        import json

        header = (
            base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "test-kid"}).encode())
            .rstrip(b"=")
            .decode()
        )
        payload = (
            base64.urlsafe_b64encode(json.dumps({"iss": DEFAULT_TEST_ISSUER, "sub": "x"}).encode())
            .rstrip(b"=")
            .decode()
        )
        token = f"{header}.{payload}."

        with pytest.raises(InvalidToken, match="not allowed"):
            await auth_env.auth_guard.verify(token)

    async def test_missing_kid_rejected(self, auth_env: TestAuthEnvironment):
        # Build a normal token then mangle the header.
        import base64
        import json

        token = auth_env.token()
        parts = token.split(".")
        header = json.loads(base64.urlsafe_b64decode(parts[0] + "==").decode())
        header.pop("kid", None)
        new_header = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
        token = ".".join([new_header, parts[1], parts[2]])
        with pytest.raises(InvalidToken, match="missing 'kid'"):
            await auth_env.auth_guard.verify(token)


# ----------------------------------------------------------- issuer / signature


class TestIssuerAndSignature:
    async def test_unregistered_issuer_rejected(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(issuer="https://foreign.example.com/realms/x")
        with pytest.raises(InvalidToken, match="not registered"):
            await auth_env.auth_guard.verify(token)

    async def test_signature_from_different_keypair_rejected(self, auth_env: TestAuthEnvironment):
        # Token signed by a *different* keypair → InvalidToken.
        from platform_auth.testing import TestKeypair

        rogue = TestKeypair(kid="test-kid")  # same kid, different key
        token = build_test_token(
            keypair=rogue,
            audience=DEFAULT_TEST_AUDIENCE,
            issuer=DEFAULT_TEST_ISSUER,
        )
        with pytest.raises(InvalidToken, match="signature mismatch"):
            await auth_env.auth_guard.verify(token)


# ---------------------------------------------------------- audience / expiry


class TestAudienceAndExpiry:
    async def test_wrong_audience(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(audience="svc-different")
        with pytest.raises(InvalidToken, match="audience mismatch"):
            await auth_env.auth_guard.verify(token)

    async def test_expired_token(self, auth_env: TestAuthEnvironment):
        # exp 60s in the past, well outside the default 30s clock skew.
        token = auth_env.token(exp_seconds=-60)
        with pytest.raises(TokenExpired):
            await auth_env.auth_guard.verify(token)

    async def test_nbf_in_future(self, auth_env: TestAuthEnvironment):
        # nbf 600s in the future.
        token = auth_env.token(nbf_offset_seconds=600)
        with pytest.raises(InvalidToken, match="not yet valid"):
            await auth_env.auth_guard.verify(token)


# ---------------------------------------------------------- claim validation


class TestClaimValidation:
    async def test_missing_required_claim(self, auth_env: TestAuthEnvironment):
        # Sign a token missing 'jti' explicitly.
        token = auth_env.token(jti="placeholder")
        # We'll need to patch — easier to mint manually.
        import time
        import uuid

        from platform_auth.auth_guard import DEFAULT_TENANT_ID_CLAIM

        now = int(time.time())
        claims = {
            "iss": DEFAULT_TEST_ISSUER,
            "aud": DEFAULT_TEST_AUDIENCE,
            "sub": "user-1",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            # 'jti' absent
            DEFAULT_TENANT_ID_CLAIM: str(DEFAULT_TEST_TENANT_ID),
        }
        token = auth_env.keypair.sign(claims)
        del uuid  # silence unused import lint

        with pytest.raises(InvalidToken, match="missing required claim"):
            await auth_env.auth_guard.verify(token)

    async def test_token_without_nbf_is_accepted(self, auth_env: TestAuthEnvironment):
        """Regression: ``nbf`` is OPTIONAL per RFC 7519 §4.1.5 / RFC 9068.
        Keycloak (and most IdPs) omit it by default. The verifier must
        accept tokens missing ``nbf`` as long as every truly-required
        claim is present. Without this, real Keycloak tokens get
        rejected by AuthGuard with ``missing required claim: nbf`` —
        the bug the SPA hit post platform-auth migration."""
        import time

        from platform_auth.auth_guard import DEFAULT_TENANT_ID_CLAIM

        now = int(time.time())
        claims = {
            "iss": DEFAULT_TEST_ISSUER,
            "aud": DEFAULT_TEST_AUDIENCE,
            "sub": "user-1",
            "iat": now,
            "exp": now + 900,
            "jti": "no-nbf-jti",
            # ``nbf`` intentionally absent.
            DEFAULT_TENANT_ID_CLAIM: str(DEFAULT_TEST_TENANT_ID),
        }
        token = auth_env.keypair.sign(claims)
        identity = await auth_env.auth_guard.verify(token)
        assert identity.subject == "user-1"

    async def test_missing_tenant_claim(self, auth_env: TestAuthEnvironment):
        import time

        now = int(time.time())
        claims = {
            "iss": DEFAULT_TEST_ISSUER,
            "aud": DEFAULT_TEST_AUDIENCE,
            "sub": "user-1",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "jti": "test-jti",
            # Tenant claim absent
        }
        token = auth_env.keypair.sign(claims)
        with pytest.raises(InvalidToken, match="missing tenant claim"):
            await auth_env.auth_guard.verify(token)

    async def test_malformed_tenant_uuid(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(tenant_id="not-a-uuid")
        with pytest.raises(InvalidToken, match="not a valid UUID"):
            await auth_env.auth_guard.verify(token)


# ---------------------------------------------------------- trust-map paths


class TestTrustMap:
    async def test_unknown_tenant_rejected(self, auth_env: TestAuthEnvironment):
        unknown_tenant = UUID("99999999-9999-9999-9999-999999999999")
        token = auth_env.token(tenant_id=unknown_tenant)
        with pytest.raises(InvalidToken, match="unknown tenant"):
            await auth_env.auth_guard.verify(token)

    async def test_mismatched_issuer_raises_issuer_not_trusted(self, auth_env: TestAuthEnvironment):
        # Tenant A is registered with default issuer; mint a token claiming
        # tenant A but from issuer B (also registered, but wrong for this tenant).
        rogue_issuer = "https://idp.test/realms/rogue"
        auth_env.jwks_cache.register_issuer(
            rogue_issuer, f"{rogue_issuer}/protocol/openid-connect/certs"
        )
        # The rogue issuer URL points at the same JWKS server (same keypair),
        # so signature verification passes — only the trust-map check should fail.
        token = build_test_token(
            keypair=auth_env.keypair,
            issuer=rogue_issuer,
            audience=DEFAULT_TEST_AUDIENCE,
        )
        with pytest.raises(IssuerNotTrusted):
            await auth_env.auth_guard.verify(token)

    async def test_suspended_tenant(self, auth_env: TestAuthEnvironment):
        auth_env.trust_map.suspend(DEFAULT_TEST_TENANT_ID)
        token = auth_env.token()
        with pytest.raises(TenantSuspended):
            await auth_env.auth_guard.verify(token)


# ------------------------------------------------------------- revocation


class TestRevocation:
    async def test_revoked_jti(self, auth_env: TestAuthEnvironment):
        from fakeredis import aioredis as fakeaioredis

        redis = fakeaioredis.FakeRedis(decode_responses=False)
        revocation = RevocationStore(redis)
        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            revocation=revocation,
        )

        token = auth_env.token(jti="bad-jti")
        await revocation.add("bad-jti", ttl_seconds=900)

        try:
            with pytest.raises(TokenRevoked):
                await guard.verify(token)
        finally:
            await redis.aclose()


# ------------------------------------------------------------ act chain


class TestActChain:
    async def test_authorized_actor_returns_identity(self, auth_env: TestAuthEnvironment):
        # Use a more restrictive policy than the default permissive one.
        policy = StaticMayActPolicy({DEFAULT_TEST_AUDIENCE: ["svc-deepagent"]})
        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            may_act=policy,
        )
        token = auth_env.token(act={"client_id": "svc-deepagent", "sub": "svc-deepagent"})
        identity = await guard.verify(token)
        assert identity.actor == "svc-deepagent"
        assert identity.is_actor

    async def test_unauthorized_actor_rejected(self, auth_env: TestAuthEnvironment):
        policy = StaticMayActPolicy({DEFAULT_TEST_AUDIENCE: ["svc-deepagent"]})
        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            may_act=policy,
        )
        token = auth_env.token(act={"client_id": "svc-rogue"})
        with pytest.raises(ActorNotAuthorized, match="svc-rogue"):
            await guard.verify(token)

    async def test_act_chain_each_hop_authorized(self, auth_env: TestAuthEnvironment):
        # Two-hop chain: B acted as A, then both call us.
        policy = StaticMayActPolicy({DEFAULT_TEST_AUDIENCE: ["svc-a", "svc-b"]})
        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            may_act=policy,
        )
        token = auth_env.token(act=[{"client_id": "svc-b"}, {"client_id": "svc-a"}])
        identity = await guard.verify(token)
        # Outermost actor is reported (the one that minted this token).
        assert identity.actor == "svc-b"

    async def test_act_chain_unauthorized_at_inner_hop(self, auth_env: TestAuthEnvironment):
        policy = StaticMayActPolicy({DEFAULT_TEST_AUDIENCE: ["svc-b"]})
        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            may_act=policy,
        )
        # svc-b is authorized but svc-a-rogue is not.
        token = auth_env.token(act=[{"client_id": "svc-b"}, {"client_id": "svc-a-rogue"}])
        with pytest.raises(ActorNotAuthorized, match="svc-a-rogue"):
            await guard.verify(token)

    async def test_act_missing_identifier_rejected(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(act={"foo": "bar"})  # no client_id/azp/sub
        with pytest.raises(InvalidToken, match="missing actor identifier"):
            await auth_env.auth_guard.verify(token)

    async def test_act_not_object_rejected(self, auth_env: TestAuthEnvironment):
        token = auth_env.token(extra_claims={"act": "not-an-object"})
        with pytest.raises(InvalidToken, match="must be an object"):
            await auth_env.auth_guard.verify(token)

    async def test_act_chain_too_deep_rejected(self, auth_env: TestAuthEnvironment):
        # 11 hops > the 10 limit.
        chain = [{"client_id": f"svc-hop-{i}"} for i in range(11)]
        token = auth_env.token(act=chain)
        with pytest.raises(InvalidToken, match="too deep"):
            await auth_env.auth_guard.verify(token)


# ---------------------------------------------------------------- audit


class TestAudit:
    async def test_audit_callback_invoked_on_allow(self, auth_env: TestAuthEnvironment):
        records: list[dict[str, Any]] = []

        def hook(record):
            records.append(dict(record))

        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            audit=hook,
        )
        token = auth_env.token()
        await guard.verify(token)
        assert len(records) == 1
        assert records[0]["decision"] == "allow"
        assert records[0]["audience"] == auth_env.audience
        assert records[0]["tenant_id"] == str(DEFAULT_TEST_TENANT_ID)

    async def test_async_audit_callback_awaited(self, auth_env: TestAuthEnvironment):
        records: list[dict[str, Any]] = []

        async def hook(record):
            await asyncio.sleep(0)
            records.append(dict(record))

        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            audit=hook,
        )
        token = auth_env.token()
        await guard.verify(token)
        assert len(records) == 1

    async def test_audit_record_carries_tenant_slug(self, auth_env: TestAuthEnvironment):
        """Cross-SDK audit-record contract: when ``IdentityContext.tenant_slug``
        is populated, the captured record's ``tenant_slug`` field carries it.

        Mirrors the Rust ``audit_callback_propagates_tenant_slug`` cargo test
        and Node's audit propagation. A regression that drops the field from
        ``_emit_audit`` (or stops reading ``identity.tenant_slug``) gets
        caught here.
        """
        records: list[dict[str, Any]] = []

        def hook(record):
            records.append(dict(record))

        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            audit=hook,
        )
        token = auth_env.token(tenant_slug="acme-corp")
        await guard.verify(token)
        assert len(records) == 1
        assert records[0]["tenant_slug"] == "acme-corp"

    async def test_audit_record_tenant_slug_is_none_when_claim_absent(
        self, auth_env: TestAuthEnvironment
    ):
        """When the JWT carries no slug claim, the audit record's
        ``tenant_slug`` is ``None`` (not omitted) — pinned so downstream
        pipelines can rely on a stable schema."""
        records: list[dict[str, Any]] = []

        def hook(record):
            records.append(dict(record))

        guard = AuthGuard(
            audience=auth_env.audience,
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            audit=hook,
        )
        token = auth_env.token()  # no tenant_slug
        await guard.verify(token)
        assert len(records) == 1
        assert records[0]["tenant_slug"] is None

    async def test_audit_callback_does_not_fire_on_deny(
        self, auth_env: TestAuthEnvironment
    ):
        """Cross-SDK forward-compat parity: Python + Node + Rust all
        currently emit on the allow path only. Deny is reserved as an
        extension point all three SDKs flip together. Pinned here so a
        future change to fire on deny lands across all three SDKs in
        lockstep instead of drifting one ahead.

        Mirrors Rust's ``audit_callback_does_not_fire_on_deny`` and
        Node's ``does not fire on the deny path`` test.
        """
        records: list[dict[str, Any]] = []

        def hook(record):
            records.append(dict(record))

        # Verifier expects an audience the token doesn't carry → reject.
        guard = AuthGuard(
            audience="wrong-audience",
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
            audit=hook,
        )
        token = auth_env.token()
        with pytest.raises(InvalidToken):
            await guard.verify(token)
        assert records == []


# ------------------------------------------------------ constructor validation


class TestConstructorValidation:
    async def test_empty_audience_rejected(self, auth_env: TestAuthEnvironment):
        with pytest.raises(ValueError, match="audience must be non-empty"):
            AuthGuard(audience="", jwks=auth_env.jwks_cache)

    async def test_alg_none_in_allowlist_rejected(self, auth_env: TestAuthEnvironment):
        with pytest.raises(ValueError, match="forbidden"):
            AuthGuard(
                audience=auth_env.audience,
                jwks=auth_env.jwks_cache,
                algorithms=("RS256", "none"),
            )

    async def test_empty_algorithms_rejected(self, auth_env: TestAuthEnvironment):
        with pytest.raises(ValueError, match="algorithms must be non-empty"):
            AuthGuard(
                audience=auth_env.audience,
                jwks=auth_env.jwks_cache,
                algorithms=(),
            )

    async def test_negative_clock_skew_rejected(self, auth_env: TestAuthEnvironment):
        with pytest.raises(ValueError, match="clock_skew_seconds must be"):
            AuthGuard(
                audience=auth_env.audience,
                jwks=auth_env.jwks_cache,
                clock_skew_seconds=-1,
            )

    async def test_audience_and_audiences_together_rejected(
        self, auth_env: TestAuthEnvironment
    ):
        with pytest.raises(ValueError, match="provide either audience or audiences"):
            AuthGuard(
                audience="svc-a",
                audiences=("svc-a", "svc-b"),
                jwks=auth_env.jwks_cache,
            )

    async def test_empty_audiences_rejected(self, auth_env: TestAuthEnvironment):
        with pytest.raises(ValueError, match="audiences must be non-empty"):
            AuthGuard(audiences=(), jwks=auth_env.jwks_cache)

    async def test_audiences_with_blank_entry_rejected(
        self, auth_env: TestAuthEnvironment
    ):
        with pytest.raises(ValueError, match="audience entries must be non-empty"):
            AuthGuard(audiences=("svc-a", ""), jwks=auth_env.jwks_cache)

    async def test_neither_audience_nor_audiences_rejected(
        self, auth_env: TestAuthEnvironment
    ):
        # Calling without either must fail closed — silently accepting any
        # audience would be a security regression.
        with pytest.raises(ValueError, match="audience must be non-empty"):
            AuthGuard(jwks=auth_env.jwks_cache)


# --------------------------------------------------- multi-audience verification


class TestPluralAudiences:
    """Plural ``audiences`` is the dual-issuer migration contract.

    During the gatekeeper-mints-internal-JWT migration, backends accept
    tokens with either the legacy Keycloak audience (``gatekeeper``) or the
    new internal-token audience (``platform-services``). Both must verify
    on the same AuthGuard instance.
    """

    async def test_audience_property_falls_back_to_first(
        self, auth_env: TestAuthEnvironment
    ):
        guard = AuthGuard(
            audiences=("primary", "secondary"),
            jwks=auth_env.jwks_cache,
        )
        assert guard.audience == "primary"
        assert guard.audiences == ("primary", "secondary")

    async def test_singular_audience_back_compat_property(
        self, auth_env: TestAuthEnvironment
    ):
        guard = AuthGuard(audience="only-one", jwks=auth_env.jwks_cache)
        assert guard.audience == "only-one"
        assert guard.audiences == ("only-one",)

    async def test_token_matching_first_audience_accepted(
        self, auth_env: TestAuthEnvironment
    ):
        guard = AuthGuard(
            audiences=(auth_env.audience, "platform-services"),
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
        )
        token = auth_env.token()  # default audience = auth_env.audience
        identity = await guard.verify(token)
        assert identity.subject == "test-user-1"

    async def test_token_matching_secondary_audience_accepted(
        self, auth_env: TestAuthEnvironment
    ):
        guard = AuthGuard(
            audiences=(auth_env.audience, "platform-services"),
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
        )
        token = auth_env.token(audience="platform-services")
        identity = await guard.verify(token)
        assert identity.subject == "test-user-1"

    async def test_token_matching_no_audience_rejected(
        self, auth_env: TestAuthEnvironment
    ):
        guard = AuthGuard(
            audiences=(auth_env.audience, "platform-services"),
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
        )
        token = auth_env.token(audience="some-other-svc")
        with pytest.raises(InvalidToken, match="audience mismatch"):
            await guard.verify(token)

    async def test_audience_mismatch_message_lists_all_expected(
        self, auth_env: TestAuthEnvironment
    ):
        guard = AuthGuard(
            audiences=("svc-a", "svc-b"),
            jwks=auth_env.jwks_cache,
            trust_map=auth_env.trust_map,
        )
        token = auth_env.token(audience="svc-c")
        with pytest.raises(InvalidToken) as exc_info:
            await guard.verify(token)
        message = str(exc_info.value)
        assert "svc-a" in message
        assert "svc-b" in message


# ----------------------------------------------------- request.state robustness


class TestRequestStateRobustness:
    async def test_state_attribute_missing_does_not_raise(self, auth_env: TestAuthEnvironment):
        # Some test doubles use plain dicts instead of SimpleNamespace; ensure
        # we don't blow up trying to set attribute.
        class StatelessRequest:
            def __init__(self, headers):
                self.headers = headers

            # No `state` attribute, no `__setattr__` shenanigans.

        token = auth_env.token()
        identity = await auth_env.auth_guard(StatelessRequest(bearer_headers(token)))
        assert identity.subject == "test-user-1"


# ------------------------------------------------- jwks-cache interplay


class TestJWKSCacheInterplay:
    async def test_unknown_kid_in_active_jwks_yields_invalid_token(
        self, auth_env: TestAuthEnvironment
    ):
        # Build a token whose header claims kid='no-such-kid' but otherwise
        # valid. The JWKS document only contains 'test-kid', so the cache
        # should refresh and still not find it.
        from platform_auth.testing import TestKeypair

        rogue_kid_keypair = TestKeypair(kid="no-such-kid")
        # We need the token signed AS rogue_kid_keypair so the header has
        # kid='no-such-kid' — but the active JWKS doesn't contain it.
        token = build_test_token(
            keypair=rogue_kid_keypair,
            audience=DEFAULT_TEST_AUDIENCE,
            issuer=DEFAULT_TEST_ISSUER,
        )
        with pytest.raises(InvalidToken, match="unknown signing key"):
            await auth_env.auth_guard.verify(token)


# ----------------------------------------------------------- standalone setup


class TestStandaloneSetup:
    """Sanity check: the SDK can be wired without the test fixture
    convenience layer, mirroring how a service will wire it in production."""

    async def test_minimal_setup(self):
        from platform_auth.testing import (
            DEFAULT_TEST_AUDIENCE,
            DEFAULT_TEST_ISSUER,
            TestKeypair,
            build_test_token,
        )

        keypair = TestKeypair()
        jwks = make_jwks_cache(keypair, issuer=DEFAULT_TEST_ISSUER)
        try:
            guard = AuthGuard(audience=DEFAULT_TEST_AUDIENCE, jwks=jwks)
            token = build_test_token(
                keypair=keypair,
                audience=DEFAULT_TEST_AUDIENCE,
                issuer=DEFAULT_TEST_ISSUER,
            )
            identity = await guard.verify(token)
            assert identity.tenant_id == DEFAULT_TEST_TENANT_ID
        finally:
            await jwks.aclose()

"""Python parity runner — verifies the forge-shipped Python SDK
matches every cross-language scenario in ``scenarios.py``.

Skipped when the SDK's optional runtime deps (``PyJWT``, ``httpx``,
``cryptography``) aren't installed in forge's dev venv. Production
CI activates them via:

    uv run --with PyJWT --with httpx --with cryptography \\
        pytest tests/contract/auth_sdk_parity/test_python_runner.py

Forge's normal ``pytest`` invocation skips this file silently — the
parity contract still runs at the SDK-shipped level (the SDK ships
its own ``tests/`` tree as a forge fragment, and *those* tests run
inside the generated project's venv where the deps are installed
by definition).

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 9 deliverables).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

# Skip the whole file if any SDK runtime dep is missing.
pyjwt = pytest.importorskip("jwt")
httpx = pytest.importorskip("httpx")
pytest.importorskip("redis")
pytest.importorskip("cachetools")
crypto_serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
crypto_ec = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ec")

# Add the forge-shipped SDK template's src/ to sys.path so we can
# ``import platform_auth``. The fragment template is at
# ``forge/features/auth/templates/platform_auth_sdk/python/files/sdks/platform-auth/src/``.
REPO_ROOT = Path(__file__).resolve().parents[3]
_SDK_SRC = (
    REPO_ROOT
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_sdk"
    / "python"
    / "files"
    / "sdks"
    / "platform-auth"
    / "src"
)
if str(_SDK_SRC) not in sys.path:
    sys.path.insert(0, str(_SDK_SRC))

# Now safe to import — the SDK uses ``from platform_auth.auth_guard
# import ...`` style, so the package needs to be importable from the
# top of sys.path.
from platform_auth import (  # noqa: E402
    AuthError,
    AuthGuard,
    InMemoryIssuerTrustMap,
    InvalidToken,
    JWKSCache,
    StaticMayActPolicy,
    TenantTrust,
    TokenExpired,
    TokenRevoked,
)
from platform_auth.exceptions import (  # noqa: E402
    ActorNotAuthorized,
    IssuerNotTrusted,
    TenantSuspended,
)
from platform_auth.revocation import RevocationStore  # noqa: E402

from tests.contract.auth_sdk_parity.scenarios import (  # noqa: E402
    ISSUER,
    SCENARIOS,
    Scenario,
)


# ---------------------------------------------------------------- helpers


def _gen_keypair() -> tuple[Any, dict[str, Any], str]:
    """Generate an ES256 keypair + the JWK shape JWKS expects.

    Returns (private_key, jwks_document, kid).
    """
    private_key = crypto_ec.generate_private_key(crypto_ec.SECP256R1())
    public_key = private_key.public_key()

    # Encode the public key as a JWK (EC P-256). The SDK's JWKSCache
    # parses these via PyJWT's PyJWK constructor.
    public_numbers = public_key.public_numbers()

    def _b64url_uint(n: int) -> str:
        import base64

        # ECDSA P-256 coordinates are 32 bytes (256 bits) each.
        b = n.to_bytes(32, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    kid = f"test-key-{uuid.uuid4().hex[:8]}"
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_uint(public_numbers.x),
        "y": _b64url_uint(public_numbers.y),
        "kid": kid,
        "alg": "ES256",
        "use": "sig",
    }
    jwks = {"keys": [jwk]}
    return private_key, jwks, kid


def _mint_token(scenario: Scenario, private_key: Any, kid: str) -> str:
    """Mint a JWT for the scenario using PyJWT directly.

    The scenario's `algorithm` field controls the JWT alg header;
    negative-test paths (`none`, `HS256`) inject the wrong alg here
    so the verifier exercises its alg-allowlist enforcement.
    """
    now = int(time.time())
    issued_at = now + (scenario.issued_at or 0)
    expires_at = (
        scenario.expires_at if scenario.expires_at and scenario.expires_at != 0
        else issued_at + scenario.ttl_seconds
    )
    # The scenario's expires_at/issued_at are negative offsets from
    # "now" — `expires_at: -1800` means "expired 30 min ago".
    if scenario.issued_at is not None:
        issued_at = now + scenario.issued_at
    if scenario.expires_at is not None:
        expires_at = now + scenario.expires_at

    audiences = (
        list(scenario.audience) if isinstance(scenario.audience, tuple)
        else [scenario.audience]
    )

    payload: dict[str, Any] = {
        "iss": scenario.issuer,
        "aud": audiences if len(audiences) > 1 else audiences[0],
        "sub": scenario.subject,
        "iat": issued_at,
        "exp": expires_at,
        "jti": scenario.jti or f"test-jti-{uuid.uuid4().hex[:8]}",
    }
    # Apply the tenant claim unless the scenario asks to omit it.
    if scenario.tenant_id_claim not in scenario.omit_claims:
        payload[scenario.tenant_id_claim] = scenario.tenant_id
    if scenario.roles:
        payload[scenario.roles_claim] = list(scenario.roles)
    if scenario.scopes:
        payload[scenario.scope_claim] = " ".join(scenario.scopes)
    if scenario.tenant_slug is not None:
        payload[scenario.tenant_slug_claim] = scenario.tenant_slug
    if scenario.act:
        payload["act"] = scenario.act
    payload.update(scenario.extra_claims)

    headers: dict[str, Any] = {}
    if "kid" not in scenario.omit_claims:
        headers["kid"] = kid

    if scenario.algorithm.lower() == "none":
        # PyJWT 2+ rejects ``none`` even with allow_unsecured=False;
        # build the token manually.
        import base64

        def _b64url(b: bytes) -> str:
            return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

        header = {"alg": "none", **headers}
        unsigned = (
            _b64url(json.dumps(header, separators=(",", ":")).encode())
            + "."
            + _b64url(json.dumps(payload, separators=(",", ":")).encode())
            + "."
        )
        return unsigned

    if scenario.algorithm == "HS256":
        # Symmetric — sign with a dummy shared secret. The verifier
        # rejects HS256 by allowlist, so it never tries to verify the
        # signature; we just need the token to be parseable.
        return pyjwt.encode(
            payload, "dummy-secret", algorithm="HS256", headers=headers
        )

    # Default ES256 — sign with the per-scenario keypair.
    return pyjwt.encode(
        payload, private_key, algorithm=scenario.algorithm, headers=headers
    )


def _build_auth_guard(
    scenario: Scenario,
    jwks: dict[str, Any],
    keypair_kid: str,
) -> AuthGuard:
    """Construct an AuthGuard from the scenario's verifier-side config.

    Pre-populates the JWKSCache with the in-memory JWKS (no real HTTP
    fetch — the cache is stuffed via httpx MockTransport).
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=jwks)
    )
    http_client = httpx.AsyncClient(transport=transport, timeout=2.0)
    cache = JWKSCache(http_client=http_client)
    # Always register the *canonical* issuer (not scenario.issuer) so
    # the rogue-issuer scenario's `iss != registered` rejection fires.
    # ``scenario.issuer`` is the *mint-side* iss claim — for the
    # negative-test case we want the verifier to only know ISSUER.
    cache.register_issuer(ISSUER, f"{ISSUER}/auth/jwks")

    audiences = (
        tuple(scenario.verifier_audience)
        if isinstance(scenario.verifier_audience, tuple)
        else (scenario.verifier_audience,)
    )

    # Trust map. Empty by default — only enabled when the scenario
    # opts in, so default scenarios don't get a "missing trust record"
    # rejection.
    trust_map = None
    if scenario.trust_map_overrides:
        records = {
            uuid.UUID(tenant_id): TenantTrust(
                expected_issuer=record["expected_issuer"],
                suspended=record.get("suspended", False),
            )
            for tenant_id, record in scenario.trust_map_overrides.items()
        }
        trust_map = InMemoryIssuerTrustMap(records)

    # MayActPolicy. Scenario semantics: ``may_act_allowlist`` is
    # keyed ``actor → tuple-of-allowed-audiences`` (the operator-
    # intuitive shape: "what audiences may svc-workflow call?").
    # All three SDKs (Python / Node / Rust) implement
    # ``StaticMayActPolicy`` keyed audience → actors at the API
    # surface — invert here so the lookup-keying matches the
    # canonical platform-auth implementation.
    may_act = None
    if scenario.may_act_allowlist:
        inverted: dict[str, set[str]] = {}
        for actor, audiences in scenario.may_act_allowlist.items():
            for audience in audiences:
                inverted.setdefault(audience, set()).add(actor)
        may_act = StaticMayActPolicy(inverted)

    revocation = (
        _DenylistStore(scenario.revocation_denylist)
        if scenario.revocation_denylist
        else None
    )

    return AuthGuard(
        audiences=audiences,
        jwks=cache,
        trust_map=trust_map,
        revocation=revocation,
        may_act=may_act,
        algorithms=tuple(scenario.verifier_algorithms),
        tenant_id_claim=scenario.verifier_tenant_id_claim,
        tenant_slug_claim=scenario.verifier_tenant_slug_claim,
        roles_claim=scenario.verifier_roles_claim,
        scope_claim=scenario.verifier_scope_claim,
    )


class _DenylistStore(RevocationStore):
    """Trivial revocation store backed by an in-memory denylist tuple."""

    def __init__(self, denylist: tuple[str, ...]) -> None:
        self._denylist = frozenset(denylist)

    async def is_revoked(self, jti: str) -> bool:
        return jti in self._denylist


# Map cross-language slugs to Python AuthError subclasses.
_SLUG_TO_EXCEPTION = {
    "invalid_token": InvalidToken,
    "token_expired": TokenExpired,
    "token_revoked": TokenRevoked,
    "issuer_not_trusted": IssuerNotTrusted,
    "actor_not_authorized": ActorNotAuthorized,
    "tenant_suspended": TenantSuspended,
}


# ---------------------------------------------------------------- runner


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
@pytest.mark.asyncio
async def test_python_sdk_matches_scenario(scenario: Scenario) -> None:
    """The Python SDK's verification outcome matches the scenario spec.

    For scenarios expecting success, asserts the IdentityContext's
    tenant/subject/roles/scopes/actor match the expected values. For
    scenarios expecting failure, asserts the right AuthError subclass
    is raised (mapped from the cross-language slug).
    """
    # Mint a fresh keypair per scenario so test order doesn't matter.
    private_key, jwks, kid = _gen_keypair()

    # Build the verifier — populates the JWKSCache via mock transport.
    auth_guard = _build_auth_guard(scenario, jwks, kid)

    # Mint the token from the scenario's inputs.
    token = _mint_token(scenario, private_key, kid)

    if scenario.expected.identity is not None:
        # Success path.
        identity = await auth_guard.verify(token)
        expected = scenario.expected.identity
        assert str(identity.tenant_id) == expected["tenant_id"]
        assert identity.subject == expected["subject"]
        assert sorted(identity.roles) == sorted(expected.get("roles", []))
        assert sorted(identity.scopes) == sorted(expected.get("scopes", []))
        assert identity.actor == expected.get("actor")
        # Optional tenant_slug — assert when the scenario pins it; an
        # absent expectation key means "any value is fine" (back-compat
        # for scenarios written before the field shipped).
        if "tenant_slug" in expected:
            assert identity.tenant_slug == expected["tenant_slug"]
        if "is_platform_admin" in expected:
            assert identity.is_platform_admin == expected["is_platform_admin"]
    else:
        # Failure path.
        slug = scenario.expected.error
        assert slug is not None
        expected_exc = _SLUG_TO_EXCEPTION.get(slug)
        assert expected_exc is not None, f"unknown slug {slug!r}"
        with pytest.raises(expected_exc) as exc_info:
            await auth_guard.verify(token)
        if scenario.expected.error_message_contains:
            message = str(exc_info.value)
            assert scenario.expected.error_message_contains.lower() in message.lower(), (
                f"scenario {scenario.name!r}: expected message containing "
                f"{scenario.expected.error_message_contains!r}, got {message!r}"
            )

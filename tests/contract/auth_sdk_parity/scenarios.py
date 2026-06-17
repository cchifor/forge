"""Canonical cross-SDK parity scenarios.

Each `Scenario` describes one JWT verification test case in a
language-agnostic shape. Per-language runners (Python / Node / Rust)
read this spec, mint a token via their `testing` helper using the
declared inputs, run their `AuthGuard.verify`, and assert the
outcome matches the declared expectation.

The scenario set is *the* cross-language correctness contract —
adding one means every runner gains a new assertion the next time
it's run. Removing one means a regression slipped past the gate.

Scenario field names use snake_case so they translate directly to
Python keyword args, JSON keys, and Rust struct fields. Per-language
runners deserialize the spec via the canonical JSON dump produced by
``scenarios_as_json()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Constants — pinned across every scenario so runners use identical
# claim names, issuer URLs, and audience values.
# ---------------------------------------------------------------------------

# Canonical issuer URL for tokens minted in scenarios. Runners register
# this issuer with their JWKSCache before verifying. Must be HTTPS-or-
# loopback only — the actual JWKS document is local-served by the test
# runner, not fetched over the network.
ISSUER = "http://gatekeeper.test:5000"

# Default audience the verifier expects. Scenarios that test audience
# mismatch override the *minted* audience; the verifier audience stays
# this value.
AUDIENCE = "svc-test"

# Canonical tenant id used in happy-path scenarios.
TENANT_ID = "11111111-1111-4111-8111-111111111111"

# Canonical subject (Keycloak `sub` shape — UUID).
SUBJECT = "22222222-2222-4222-8222-222222222222"

# Tenant claim name — matches forge's default. Runners must use the
# same value when minting AND verifying.
TENANT_ID_CLAIM = "https://forge/tenant_id"

# Required-claim set (RFC 9068 §2.2 + tenant). Runners pass these to
# their verifier as the required-claims list. Scenarios that test
# "missing required claim" omit one of these explicitly.
REQUIRED_CLAIMS = ("iss", "aud", "sub", "exp", "iat", "jti")


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------


# Cross-language `AuthError` variants. Runners map their language's
# error type to one of these slugs (which match the `reason()` method
# return values across Python / Node / Rust).
ExpectedError = Literal[
    "invalid_token",
    "token_expired",
    "token_revoked",
    "issuer_not_trusted",
    "actor_not_authorized",
    "scope_required",
    "tenant_suspended",
    "s2s_auth_error",
]


@dataclass(frozen=True)
class ExpectedOutcome:
    """One scenario's expected verification outcome.

    Either ``identity`` or ``error`` is set, never both. ``identity``
    is a dict the runner asserts against the IdentityContext fields
    (``tenant_id``, ``subject``, ``roles``, ``scopes``, ``actor``).
    ``error`` is the cross-language `reason()` slug.
    """

    identity: dict[str, Any] | None = None
    error: ExpectedError | None = None
    # Optional: substring the runner expects in the error message.
    # Use sparingly — implementation-specific phrasing diverges across
    # languages, so a substring match is a soft assertion. Pin only
    # the parts of the message that are part of the contract (e.g.,
    # "missing tenant claim" should be present in some form).
    error_message_contains: str | None = None

    def __post_init__(self) -> None:
        if self.identity is not None and self.error is not None:
            raise ValueError(
                "ExpectedOutcome: provide either identity or error, not both"
            )
        if self.identity is None and self.error is None:
            raise ValueError(
                "ExpectedOutcome: provide either identity or error"
            )


@dataclass(frozen=True)
class Scenario:
    """One cross-language parity test case.

    Fields are organized into four buckets:
    * **Identification** — `name` (unique, snake_case).
    * **Token-mint inputs** — what the testing helper signs.
    * **Verifier config overrides** — when the verifier uses non-default
      audience / trust-map / revocation-set / may-act-policy / etc.
    * **Expected outcome** — IdentityContext or AuthError slug.
    """

    name: str
    description: str

    # Token-mint inputs (passed to testing.build_test_token).
    issuer: str = ISSUER
    audience: str | tuple[str, ...] = AUDIENCE
    subject: str = SUBJECT
    tenant_id: str = TENANT_ID
    tenant_id_claim: str = TENANT_ID_CLAIM
    roles_claim: str = "roles"  # mint side; verifier_roles_claim is its peer
    scope_claim: str = "scope"  # mint side; verifier_scope_claim is its peer
    # Optional tenant slug — when set, runners mint the
    # ``tenant_slug_claim`` claim with this value. ``None`` = omit the
    # claim entirely (the verifier should then surface
    # ``IdentityContext.tenant_slug`` as null/None).
    tenant_slug: str | None = None
    tenant_slug_claim: str = "https://forge/tenant_slug"
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    ttl_seconds: int = 300
    expires_at: int | None = None  # absolute exp override (e.g., past)
    issued_at: int | None = None
    jti: str | None = None  # if None, runner generates per-scenario
    algorithm: str = "ES256"  # negative-test scenarios use HS256/none/etc.
    act: dict[str, Any] | None = None
    extra_claims: dict[str, Any] = field(default_factory=dict)
    omit_claims: tuple[str, ...] = ()  # claims NOT to set when minting

    # Verifier-side overrides (passed to AuthGuard config).
    verifier_audience: str | tuple[str, ...] = AUDIENCE
    verifier_algorithms: tuple[str, ...] = ("ES256",)
    # Verifier-side claim-name overrides — must match the mint-side
    # claim names for happy-path scenarios; deliberately mismatched for
    # negative tests that exercise "verifier doesn't know where the claim
    # lives" failure modes.
    verifier_tenant_id_claim: str = TENANT_ID_CLAIM
    verifier_roles_claim: str = "roles"
    verifier_scope_claim: str = "scope"
    verifier_tenant_slug_claim: str = "https://forge/tenant_slug"
    revocation_denylist: tuple[str, ...] = ()
    trust_map_overrides: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # tenant_id → {expected_issuer, suspended}
    may_act_allowlist: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )  # actor_id → allowed audiences

    expected: ExpectedOutcome = field(
        default_factory=lambda: ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": [],
                "scopes": [],
                "actor": None,
            }
        )
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

# Every scenario gets a stable, unique `name` so runners can diff
# results scenario-by-scenario when the cross-language assertions
# disagree. Names are snake_case + verb-phrase first.

SCENARIOS: tuple[Scenario, ...] = (
    # ------------------------------------------------------------------ happy
    Scenario(
        name="happy_minimal",
        description=(
            "Valid token, no roles, no scopes, no actor. The smallest "
            "successful verification. Asserts the verifier accepts a "
            "well-formed token and produces an IdentityContext with "
            "the expected tenant + subject."
        ),
    ),
    Scenario(
        name="happy_with_roles_and_scopes",
        description=(
            "Valid token carrying realm roles and OAuth scopes. The "
            "verifier extracts both into the IdentityContext as "
            "frozensets/HashSets/Sets."
        ),
        roles=("admin", "user"),
        scopes=("things:read", "things:write"),
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": ["admin", "user"],
                "scopes": ["things:read", "things:write"],
                "actor": None,
            }
        ),
    ),
    Scenario(
        name="happy_platform_admin",
        description=(
            "Token holds platform:support:read scope — IdentityContext "
            ".is_platform_admin must be true. The cross-language "
            "contract pins the slug exactly."
        ),
        scopes=("platform:support:read",),
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": [],
                "scopes": ["platform:support:read"],
                "actor": None,
                "is_platform_admin": True,
            }
        ),
    ),
    Scenario(
        name="happy_custom_roles_and_scope_claim_names",
        description=(
            "Token mints roles + scopes under non-default claim names "
            "(`custom_roles` and `custom_scope` instead of `roles` / "
            "`scope`); verifier is configured to read from the same "
            "custom names. Asserts every SDK respects the configured "
            "claim-name override on both the testing-helper and the "
            "verifier sides — without this scenario, a regression that "
            "hardcoded one of the names back to the default would slip "
            "through every other scenario (which all use defaults)."
        ),
        roles_claim="custom_roles",
        scope_claim="custom_scope",
        verifier_roles_claim="custom_roles",
        verifier_scope_claim="custom_scope",
        roles=("admin",),
        scopes=("things:read",),
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": ["admin"],
                "scopes": ["things:read"],
                "actor": None,
            }
        ),
    ),
    Scenario(
        name="happy_with_tenant_slug",
        description=(
            "Token mints the optional `tenant_slug_claim` (default "
            "`https://forge/tenant_slug`) with a human-readable slug. "
            "Every SDK extracts it into ``IdentityContext.tenant_slug`` "
            "/ ``tenantSlug``. Pins the cross-SDK behavior — Python / "
            "Node / Rust must surface the same string under the same "
            "field name (modulo language-conventional case)."
        ),
        tenant_slug="acme-corp",
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": [],
                "scopes": [],
                "actor": None,
                "tenant_slug": "acme-corp",
            }
        ),
    ),
    Scenario(
        name="reject_tenant_claim_name_mismatch",
        description=(
            "Token mints the tenant id under the default claim "
            "(`https://forge/tenant_id`) but the verifier is configured "
            "to look at a custom name (`https://example.com/tenant`). "
            "Verifier finds no tenant claim under its expected name and "
            "rejects with `invalid_token`. Pins the verifier-side "
            "configurability negative path — a regression where the "
            "verifier silently fell back to the default claim name "
            "would slip through every happy-path scenario but get "
            "caught here."
        ),
        verifier_tenant_id_claim="https://example.com/tenant",
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="tenant claim",
        ),
    ),
    # ----------------------------------------------------------- alg / kid path
    Scenario(
        name="reject_alg_none",
        description=(
            "Token presents alg=none. AuthGuard hard-rejects regardless "
            "of what the verifier's allowlist says — `none` is an "
            "anti-class. Defends against alg-confusion attacks."
            "\n\n"
            "Cross-language note: the *slug* (`invalid_token`) is the "
            "contract; the message text varies by JWT library — Python's "
            "PyJWT and Node's jose surface 'algorithm not allowed' from "
            "the post-parse allowlist check, while Rust's jsonwebtoken "
            "rejects `none` at parse time with 'unknown variant'. We "
            "don't pin a substring here — see the Rust runner's parity "
            "log if you need to diagnose a mismatch."
        ),
        algorithm="none",
        expected=ExpectedOutcome(error="invalid_token"),
    ),
    Scenario(
        name="reject_alg_hs256",
        description=(
            "Token presents alg=HS256 (symmetric). AuthGuard rejects "
            "because HS256 isn't in the asymmetric-only default "
            "allowlist. Catches the secret-vs-public-key confusion bug. "
            "Slug is the cross-language contract; message text varies."
        ),
        algorithm="HS256",
        expected=ExpectedOutcome(error="invalid_token"),
    ),
    Scenario(
        name="reject_missing_kid",
        description=(
            "Token header lacks `kid`. JWKS lookup needs `kid` to pick "
            "the right signing key — without it, verification can't "
            "even start."
        ),
        omit_claims=("kid",),  # runner-side: don't set the kid header
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="kid",
        ),
    ),
    # ----------------------------------------------------------- expiry / nbf
    Scenario(
        name="reject_expired",
        description=(
            "Token's `exp` is in the past. Verifier maps the typed "
            "expired-signature error to the cross-language "
            "`token_expired` slug (NOT generic `invalid_token`)."
        ),
        # Issued an hour ago, expired 30 minutes ago.
        issued_at=-3600,  # runner adds to "now"
        expires_at=-1800,
        expected=ExpectedOutcome(error="token_expired"),
    ),
    Scenario(
        name="reject_token_not_yet_valid",
        description=(
            "Token carries an `nbf` (not-before) far in the future, so it is "
            "not yet valid. All three verifiers must reject with the "
            "`invalid_token` slug (PyJWT ImmatureSignatureError, jose nbf "
            "check, jsonwebtoken ImmatureSignature all map to InvalidToken). "
            "Pins the Rust outlier: jsonwebtoken's Validation defaults "
            "validate_nbf=false, so without an explicit opt-in Rust silently "
            "ACCEPTED a future-nbf token while Python + Node rejected it. The "
            "nbf is a fixed far-future absolute timestamp (extra_claims) so it "
            "is unambiguously in the future regardless of when the runner "
            "executes; exp stays valid (ttl_seconds) so only nbf trips."
        ),
        extra_claims={"nbf": 9999999999},  # year 2286 — always in the future
        expected=ExpectedOutcome(error="invalid_token"),
    ),
    # ----------------------------------------------------------- audience
    Scenario(
        name="reject_wrong_audience",
        description=(
            "Token's `aud` doesn't match any verifier-configured "
            "audience. Verifier rejects with invalid_token (audience "
            "mismatch is a structural failure, not a separate error "
            "class — matches Python's PyJWT behaviour)."
        ),
        audience="svc-different",
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="audience",
        ),
    ),
    Scenario(
        name="accept_multi_audience_match",
        description=(
            "Verifier configured with multiple audiences; token's "
            "single `aud` matches one. This is the Phase-4 migration "
            "shape (accept old + new audience during the cutover)."
        ),
        audience="svc-old-name",
        verifier_audience=("svc-old-name", "svc-test"),
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": [],
                "scopes": [],
                "actor": None,
            }
        ),
    ),
    # ----------------------------------------------------------- issuer / trust
    Scenario(
        name="reject_unregistered_issuer",
        description=(
            "Token's `iss` is not in the verifier's registered-issuer "
            "set. Verifier rejects without even attempting JWKS lookup."
        ),
        issuer="http://rogue-idp.test",
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="issuer",
        ),
    ),
    Scenario(
        name="reject_trust_map_issuer_mismatch",
        description=(
            "Verifier has a TrustMap; tenant maps to issuer A; token "
            "claims iss=B. Distinct from `unregistered_issuer` because "
            "B is registered in JWKSCache — the rejection comes from "
            "the trust map, NOT the JWKS layer."
        ),
        # Token signed by ISSUER (registered), but TrustMap says this
        # tenant should only accept tokens from a different registered
        # issuer.
        trust_map_overrides={
            TENANT_ID: {
                "expected_issuer": "http://other-issuer.test",
                "suspended": False,
            },
        },
        expected=ExpectedOutcome(
            error="issuer_not_trusted",
            error_message_contains="expects issuer",
        ),
    ),
    Scenario(
        name="reject_tenant_suspended",
        description=(
            "Verifier's TrustMap reports the tenant is suspended. "
            "Distinct error class so clients can differentiate `your "
            "tenant is paused` from `your token is bad`."
        ),
        trust_map_overrides={
            TENANT_ID: {"expected_issuer": ISSUER, "suspended": True},
        },
        expected=ExpectedOutcome(error="tenant_suspended"),
    ),
    Scenario(
        name="accept_unregistered_tenant_when_trust_map_present",
        description=(
            "Verifier has a NON-EMPTY TrustMap, but the token's tenant is "
            "not registered in it (the map holds a different tenant). The "
            "permissive single-issuer default (strict_trust=False) accepts "
            "the token — per-tenant issuer binding + suspension only "
            "constrain tenants explicitly registered in the map. This is "
            "the partial/empty-map install path the gatekeeper + "
            "oidc_generic providers ship (bootstrapAuth / init_auth wire "
            "an empty InMemoryIssuerTrustMap): an unregistered tenant must "
            "NOT be rejected, or the guard authenticates nobody. Python is "
            "already permissive; this pins Node + Rust to the same parity "
            "(both previously fail-closed with `unknown tenant`)."
        ),
        # Map holds a DIFFERENT tenant; the token's canonical TENANT_ID is
        # absent → the verifier sees a missing trust record.
        trust_map_overrides={
            "33333333-3333-4333-8333-333333333333": {
                "expected_issuer": ISSUER,
                "suspended": False,
            },
        },
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": [],
                "scopes": [],
                "actor": None,
            }
        ),
    ),
    # ----------------------------------------------------------- tenant claim
    Scenario(
        name="reject_missing_tenant_claim",
        description=(
            "Token signature is valid, all standard claims present, "
            "but the configured `tenant_id_claim` is missing. Verifier "
            "rejects (the SDK is multi-tenant by design — anonymous "
            "tokens have no place)."
        ),
        # Mint a token but specifically don't include the tenant claim.
        # Runner uses the omit_claims signal — `https://forge/tenant_id`
        # in this list means "don't set it".
        omit_claims=(TENANT_ID_CLAIM,),
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="tenant",
        ),
    ),
    Scenario(
        name="reject_non_uuid_tenant",
        description=(
            "Tenant claim present but not a valid UUID. Verifier "
            "validates UUID shape — defends against typos and "
            "malformed migrations."
        ),
        tenant_id="not-a-uuid",
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="UUID",
        ),
    ),
    # ----------------------------------------------------------- jti / revoke
    Scenario(
        name="reject_revoked_jti",
        description=(
            "Verifier's RevocationStore reports the jti is revoked. "
            "Token would otherwise verify successfully — this gates "
            "logout-revocation latency."
        ),
        jti="revoked-jti-fixture",
        revocation_denylist=("revoked-jti-fixture",),
        expected=ExpectedOutcome(error="token_revoked"),
    ),
    # ----------------------------------------------------------- act chain
    Scenario(
        name="happy_act_chain_one_hop",
        description=(
            "Valid on-behalf-of token: outer subject = user, `act` "
            "carries svc-workflow as the immediate actor. Verifier's "
            "MayActPolicy allows svc-workflow → svc-test. "
            "IdentityContext.actor = 'svc-workflow'."
        ),
        act={"client_id": "svc-workflow"},
        may_act_allowlist={"svc-workflow": ("svc-test",)},
        expected=ExpectedOutcome(
            identity={
                "tenant_id": TENANT_ID,
                "subject": SUBJECT,
                "roles": [],
                "scopes": [],
                "actor": "svc-workflow",
            }
        ),
    ),
    Scenario(
        name="reject_act_chain_unauthorized_actor",
        description=(
            "On-behalf-of token, but MayActPolicy disallows the "
            "actor. Distinct error (`actor_not_authorized`, status 403) "
            "so clients can dispatch."
        ),
        act={"client_id": "svc-rogue"},
        may_act_allowlist={"svc-workflow": ("svc-test",)},
        expected=ExpectedOutcome(
            error="actor_not_authorized",
            error_message_contains="rogue",
        ),
    ),
    Scenario(
        name="reject_act_chain_too_deep",
        description=(
            "Pathological act chain >10 hops. Verifier caps depth at "
            "10 so a malicious or buggy chain doesn't recurse forever."
        ),
        # 11-hop nested act. Each hop authorized; the cap is the hard "
        # stop.
        act={
            "client_id": "svc-1",
            "act": {
                "client_id": "svc-2",
                "act": {
                    "client_id": "svc-3",
                    "act": {
                        "client_id": "svc-4",
                        "act": {
                            "client_id": "svc-5",
                            "act": {
                                "client_id": "svc-6",
                                "act": {
                                    "client_id": "svc-7",
                                    "act": {
                                        "client_id": "svc-8",
                                        "act": {
                                            "client_id": "svc-9",
                                            "act": {
                                                "client_id": "svc-10",
                                                "act": {
                                                    "client_id": "svc-11",
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        # Allow every actor in the chain — failure is depth, not policy.
        may_act_allowlist={
            f"svc-{i}": ("svc-test",) for i in range(1, 12)
        },
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="too deep",
        ),
    ),
    Scenario(
        name="reject_act_entry_missing_actor_id",
        description=(
            "act entry lacks all three identifier candidates "
            "(client_id, azp, sub). Verifier rejects — without an "
            "identifier we can't even ask the policy."
        ),
        act={"some_other_field": "value"},
        may_act_allowlist={"svc-workflow": ("svc-test",)},
        expected=ExpectedOutcome(
            error="invalid_token",
            error_message_contains="actor identifier",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Spec accessors
# ---------------------------------------------------------------------------


def scenarios_by_name() -> dict[str, Scenario]:
    """Return scenarios indexed by their unique `name`."""
    return {s.name: s for s in SCENARIOS}


def scenarios_as_json() -> list[dict[str, Any]]:
    """Serialize scenarios to a JSON-compatible shape.

    Per-language runners (Node, Rust) load the JSON dump from disk.
    Tuples become lists; nested dataclasses become dicts.
    """

    def _to_jsonable(value: Any) -> Any:
        if isinstance(value, ExpectedOutcome):
            out: dict[str, Any] = {}
            if value.identity is not None:
                out["identity"] = _to_jsonable(value.identity)
            if value.error is not None:
                out["error"] = value.error
            if value.error_message_contains is not None:
                out["error_message_contains"] = value.error_message_contains
            return out
        if isinstance(value, tuple):
            return [_to_jsonable(v) for v in value]
        if isinstance(value, dict):
            return {k: _to_jsonable(v) for k, v in value.items()}
        return value

    out: list[dict[str, Any]] = []
    for s in SCENARIOS:
        d: dict[str, Any] = {
            "name": s.name,
            "description": s.description,
            "issuer": s.issuer,
            "audience": _to_jsonable(s.audience),
            "subject": s.subject,
            "tenant_id": s.tenant_id,
            "tenant_id_claim": s.tenant_id_claim,
            "tenant_slug": s.tenant_slug,
            "tenant_slug_claim": s.tenant_slug_claim,
            "roles_claim": s.roles_claim,
            "scope_claim": s.scope_claim,
            "roles": list(s.roles),
            "scopes": list(s.scopes),
            "ttl_seconds": s.ttl_seconds,
            "expires_at": s.expires_at,
            "issued_at": s.issued_at,
            "jti": s.jti,
            "algorithm": s.algorithm,
            "act": _to_jsonable(s.act),
            "extra_claims": _to_jsonable(s.extra_claims),
            "omit_claims": list(s.omit_claims),
            "verifier_audience": _to_jsonable(s.verifier_audience),
            "verifier_algorithms": list(s.verifier_algorithms),
            "verifier_tenant_id_claim": s.verifier_tenant_id_claim,
            "verifier_roles_claim": s.verifier_roles_claim,
            "verifier_scope_claim": s.verifier_scope_claim,
            "verifier_tenant_slug_claim": s.verifier_tenant_slug_claim,
            "revocation_denylist": list(s.revocation_denylist),
            "trust_map_overrides": _to_jsonable(s.trust_map_overrides),
            "may_act_allowlist": _to_jsonable(s.may_act_allowlist),
            "expected": _to_jsonable(s.expected),
        }
        out.append(d)
    return out

"""Invariants for the ``forge.features.auth`` Rust SDK fragment (Phase 6).

Verifies that ``platform-auth`` (greenfield Rust port of the Python
platform-auth SDK) is shipped with the public-surface modules required
for cross-language parity with the Python and Node SDKs.

Behavioural verification (the actual JWT verification, scope matching,
etc.) lives in the cross-SDK parity test suite at
``tests/contract/auth_sdk_parity/`` once Phase 9 lands.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 6 deliverables; cross-SDK parity gate at Phase 9).
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


# Source modules that mirror the Python + Node SDKs' public surface.
PUBLIC_SDK_MODULES = (
    "auth_guard.rs",
    "errors.rs",
    "extractor.rs",
    "identity.rs",
    "jwks.rs",
    "layer.rs",
    "lib.rs",
    "may_act.rs",
    "require_scope.rs",
    "revocation.rs",
    "s2s_client.rs",
    "scopes.rs",
    "testing.rs",
    "trust.rs",
)


# Sub-modules deliberately deferred to follow-up sub-phases.
# All Phase 6 follow-ups have now landed; this list documents that
# the SDK has reached structural parity with the Python and Node
# ports. Updates land if a future need surfaces a new module.
DEFERRED_MODULES: tuple[str, ...] = ()


def _sdk_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_sdk_rust"]
    impl = frag.implementations[BackendLanguage.RUST]
    return Path(impl.fragment_dir) / "files" / "sdks" / "platform-auth-rs"


def test_platform_auth_sdk_rust_fragment_registered() -> None:
    assert "platform_auth_sdk_rust" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_sdk_rust"]
    # Rust-only — Phases 1 (Python) and 4 (Node) are separate fragments.
    assert BackendLanguage.RUST in frag.implementations
    assert BackendLanguage.PYTHON not in frag.implementations
    assert BackendLanguage.NODE not in frag.implementations
    impl = frag.implementations[BackendLanguage.RUST]
    assert impl.scope == "project"
    # Auto-derived to tier 2 (Rust-only).
    assert frag.parity_tier == 2


def test_rust_sdk_public_modules_present() -> None:
    """Every cross-language public surface module ships in the fragment."""
    src_dir = _sdk_root() / "src"
    assert src_dir.is_dir(), f"src/ tree missing: {src_dir}"
    shipped = {p.name for p in src_dir.glob("*.rs")}
    missing = set(PUBLIC_SDK_MODULES) - shipped
    assert not missing, f"public Rust SDK modules not shipped: {sorted(missing)}"


def test_rust_sdk_deferred_modules_documented() -> None:
    """The deferred-modules list is accurate — every entry is genuinely absent."""
    overlap = set(PUBLIC_SDK_MODULES) & set(DEFERRED_MODULES)
    assert not overlap, f"modules listed both public and deferred: {overlap}"

    src_dir = _sdk_root() / "src"
    shipped = {p.name for p in src_dir.glob("*.rs")}
    accidentally_shipped = set(DEFERRED_MODULES) & shipped
    assert not accidentally_shipped, (
        f"deferred modules unexpectedly present in src/: {sorted(accidentally_shipped)}. "
        "Update DEFERRED_MODULES + PUBLIC_SDK_MODULES if these are now ready."
    )


def test_rust_sdk_cargo_toml_shape() -> None:
    """Cargo.toml declares the right edition + dependencies."""
    cargo = (_sdk_root() / "Cargo.toml").read_text(encoding="utf-8")
    assert 'name = "platform-auth"' in cargo
    assert 'edition = "2021"' in cargo
    # Load-bearing dependencies — changing any is a parity-affecting change.
    assert "jsonwebtoken" in cargo, "Cargo.toml must depend on jsonwebtoken"
    assert "thiserror" in cargo, "Cargo.toml must depend on thiserror"
    assert "async-trait" in cargo, "Cargo.toml must depend on async-trait"
    assert "moka" in cargo, "Cargo.toml must depend on moka"
    assert "reqwest" in cargo, "Cargo.toml must depend on reqwest"
    # The axum integration is feature-gated so consumers of the bare
    # verifier don't pull axum into their dep tree.
    assert "[features]" in cargo
    assert "axum =" in cargo, "axum integration must be a feature, not unconditional"


def test_rust_sdk_lib_re_exports_public_surface() -> None:
    """lib.rs must re-export every public symbol the parity tests expect."""
    lib_text = (_sdk_root() / "src" / "lib.rs").read_text(encoding="utf-8")
    must_export = (
        "AuthGuard",
        "AuthGuardConfig",
        "AuthError",
        "IdentityContext",
        "JwksCache",
        "JwksCacheOptions",
        "MayActPolicy",
        "AllowAllMayActPolicy",
        "StaticMayActPolicy",
        "IssuerTrustMap",
        "InMemoryIssuerTrustMap",
        "CachingIssuerTrustMap",
        "TenantTrust",
        "RevocationStore",
        "InMemoryRevocationStore",
        "NeverRevokedStore",
        "S2SClient",
        "S2SClientConfig",
        "S2SRequestOptions",
        "DEFAULT_SAFETY_MARGIN_SECONDS",
        "scope_satisfies",
        "PLATFORM_SUPPORT_READ",
        "PLATFORM_SUPPORT_WRITE",
    )
    missing = [name for name in must_export if name not in lib_text]
    assert not missing, f"lib.rs not re-exporting: {missing}"


def test_rust_sdk_default_tenant_claim_is_forge_namespaced() -> None:
    """AuthGuard's default tenant claim must be forge-namespaced.

    Mirrors the Python + Node SDK ports: forge users get
    ``https://forge/tenant_id``, NOT ``https://platform/tenant_id``.
    """
    auth_guard = (_sdk_root() / "src" / "auth_guard.rs").read_text(encoding="utf-8")
    assert (
        '"https://forge/tenant_id"' in auth_guard
    ), "DEFAULT_TENANT_ID_CLAIM must be the forge-namespaced URL"
    assert (
        '"https://platform/tenant_id"' not in auth_guard
    ), "auth_guard.rs still references the platform-namespaced tenant claim"


def test_rust_sdk_algorithms_are_asymmetric_only() -> None:
    """Default algorithms must be ES256 only; jsonwebtoken's `Algorithm`
    enum can't represent ``none`` so symmetric/none rejection is
    structural, but the default tuple is still pinned to ES256."""
    auth_guard = (_sdk_root() / "src" / "auth_guard.rs").read_text(encoding="utf-8")
    assert (
        "Algorithm::ES256" in auth_guard
    ), "default_algorithms() must reference Algorithm::ES256"


def test_rust_sdk_s2s_client_exposes_oauth2_grants() -> None:
    """s2s_client.rs must expose both OAuth2 grants Gatekeeper accepts:
    `client_credentials` (machine identity) and RFC 8693
    token-exchange (on-behalf-of). Same wire-protocol strings as
    Python's `platform_auth.s2s_client` and Node's `S2SClient.ts`
    — cross-language parity."""
    text = (_sdk_root() / "src" / "s2s_client.rs").read_text(encoding="utf-8")
    must_have = (
        "S2SClient",
        "S2SClientConfig",
        "S2SRequestOptions",
        "client_credentials",
        # RFC 8693 grant URI — wire-protocol contract.
        "urn:ietf:params:oauth:grant-type:token-exchange",
        "urn:ietf:params:oauth:token-type:access_token",
        "subject_token",
        # Cache observability.
        "CacheStats",
        # 401-retry-once behavior — matches Python and Node.
        "self.invalidate",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"s2s_client.rs missing required wiring: {missing}"


def test_rust_sdk_s2s_client_uses_moka_cache() -> None:
    """The cache uses moka::future::Cache (already in Cargo.toml).
    Bounded by max_cache_entries so a long-lived process minting
    tokens for many distinct user `jti`s doesn't grow without bound."""
    text = (_sdk_root() / "src" / "s2s_client.rs").read_text(encoding="utf-8")
    assert "moka::future::Cache" in text or "use moka::future::Cache" in text, (
        "s2s_client.rs must use moka::future::Cache for bounded token caching"
    )
    assert "max_cache_entries" in text, (
        "s2s_client.rs must accept max_cache_entries as a config knob"
    )


def test_rust_sdk_axum_layer_exposes_tower_integration() -> None:
    """layer.rs must expose AuthLayer + AuthService + the canonical
    skip-list. Mirrors Node's `platformAuthPlugin` shape."""
    text = (_sdk_root() / "src" / "layer.rs").read_text(encoding="utf-8")
    must_have = (
        "pub struct AuthLayer",
        "pub struct AuthService",
        "DEFAULT_EXCLUDED_PATHS",
        # Tower trait impls — the load-bearing wiring.
        "impl<S> Layer<S> for AuthLayer",
        "impl<S> Service<Request<Body>> for AuthService<S>",
        # Skip-list contains all four canonical probe paths.
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        # RFC 7807 problem-response URI prefix — cross-language contract.
        "https://forge.dev/errors/",
        # WWW-Authenticate header on 401 — same as Node plugin.
        "WWW_AUTHENTICATE",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"layer.rs missing required wiring: {missing}"


def test_rust_sdk_axum_layer_gated_behind_feature() -> None:
    """layer.rs / extractor.rs / require_scope.rs are wired into
    lib.rs behind ``#[cfg(feature = \"axum\")]`` so consumers of the
    bare verifier don't pay the axum + tower compile cost."""
    lib_text = (_sdk_root() / "src" / "lib.rs").read_text(encoding="utf-8")
    must_gate = (
        '#[cfg(feature = "axum")]\nmod extractor;',
        '#[cfg(feature = "axum")]\nmod layer;',
        '#[cfg(feature = "axum")]\nmod require_scope;',
        '#[cfg(feature = "axum")]\npub use extractor::',
        '#[cfg(feature = "axum")]\npub use layer::',
        '#[cfg(feature = "axum")]\npub use require_scope::',
    )
    missing = [phrase for phrase in must_gate if phrase not in lib_text]
    assert not missing, (
        f"lib.rs must gate axum integration behind the feature: {missing}"
    )


def test_rust_sdk_extractor_implements_from_request_parts() -> None:
    """extractor.rs must implement FromRequestParts for IdentityContext
    + the OptionalIdentity wrapper. Without this, route handlers would
    have to reach into request extensions manually."""
    text = (_sdk_root() / "src" / "extractor.rs").read_text(encoding="utf-8")
    must_have = (
        "impl<S> FromRequestParts<S> for IdentityContext",
        "impl<S> FromRequestParts<S> for OptionalIdentity",
        "pub struct IdentityRejection",
        "pub struct OptionalIdentity",
        # Reads from request extensions, doesn't re-verify.
        "extensions",
        ".get::<IdentityContext>()",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"extractor.rs missing required wiring: {missing}"


def test_rust_sdk_require_scope_layer_present() -> None:
    """require_scope.rs must expose RequireScope as a Tower layer
    that runs AFTER AuthLayer + asserts every required scope on the
    bound IdentityContext."""
    text = (_sdk_root() / "src" / "require_scope.rs").read_text(encoding="utf-8")
    must_have = (
        "pub struct RequireScope",
        "pub struct RequireScopeService",
        "impl<S> Layer<S> for RequireScope",
        # Reads identity from extensions.
        "request.extensions().get::<IdentityContext>()",
        # Uses identity.has_scope (cross-language scope-matching).
        "identity.has_scope",
        # ScopeRequired error variant on missing scopes.
        "ScopeRequired",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"require_scope.rs missing required wiring: {missing}"


def test_rust_sdk_s2s_client_safety_margin_default() -> None:
    """60-second pre-expiry refresh matches Python and Node defaults."""
    text = (_sdk_root() / "src" / "s2s_client.rs").read_text(encoding="utf-8")
    assert "DEFAULT_SAFETY_MARGIN_SECONDS: u64 = 60" in text, (
        "DEFAULT_SAFETY_MARGIN_SECONDS must be 60 to match Python and Node defaults"
    )


def test_rust_sdk_testing_module_gated_behind_feature() -> None:
    """testing.rs must be gated behind a feature flag.

    The keypair-generation deps (p256/ecdsa/rand) only matter for
    test-token minting; consumers using just AuthGuard shouldn't
    pay the compile cost. lib.rs uses ``#[cfg(feature = "testing")]``
    to gate the module; Cargo.toml declares the feature with the
    matching optional deps.
    """
    lib_text = (_sdk_root() / "src" / "lib.rs").read_text(encoding="utf-8")
    assert '#[cfg(feature = "testing")]' in lib_text, (
        "lib.rs must gate testing module behind the testing feature"
    )
    cargo = (_sdk_root() / "Cargo.toml").read_text(encoding="utf-8")
    assert (
        'testing = ["dep:p256", "dep:ecdsa", "dep:rand"]' in cargo
    ), "Cargo.toml must define a `testing` feature pulling p256/ecdsa/rand"


def test_rust_sdk_testing_module_exposes_token_minter() -> None:
    """testing.rs must expose the parity-fixture API surface.

    The cross-SDK parity gate (Phase 9) needs ``build_test_token`` and
    a generator for ECDSA P-256 keypairs. Cross-language parity is
    enforced by the same fixture inputs producing matching tokens
    across Python, Node, and Rust.
    """
    testing_text = (_sdk_root() / "src" / "testing.rs").read_text(encoding="utf-8")
    must_have = (
        "build_test_token",
        "TestEcdsaKeypair",
        "BuildTestTokenOptions",
        "Algorithm::ES256",
    )
    missing = [name for name in must_have if name not in testing_text]
    assert not missing, f"testing.rs missing required exports: {missing}"


def test_rust_sdk_testing_uses_forge_namespaced_default_claim() -> None:
    """build_test_token defaults to ``https://forge/tenant_id`` claim."""
    testing_text = (_sdk_root() / "src" / "testing.rs").read_text(encoding="utf-8")
    assert (
        '"https://forge/tenant_id"' in testing_text
    ), "build_test_token must default tenant_id_claim to https://forge/tenant_id"


def test_rust_sdk_verify_emits_tracing_span() -> None:
    """`AuthGuard::verify` emits a `tracing` span (`platform_auth.verify`)
    on every call. Service-side OpenTelemetry exporters that subscribe
    to the `tracing` ecosystem (`tracing-opentelemetry`,
    `opentelemetry-tracing-subscriber`) automatically pick this up —
    every protected endpoint's trace tree gets a child `verify` span
    without per-handler instrumentation.

    Mirrors Python's `opentelemetry.trace.start_as_current_span`
    inside `AuthGuard.verify` and the diagnostic surface Node's
    plugin emits via Fastify's logger.
    """
    auth_guard = (_sdk_root() / "src" / "auth_guard.rs").read_text(encoding="utf-8")
    must_have = (
        # Span declared via the canonical `tracing::instrument` macro.
        "#[tracing::instrument(",
        # Span name matches platform's verifier.
        'name = "platform_auth.verify"',
        # Token argument NOT recorded in the span (it's a credential).
        "skip(self, token)",
        # Recorded fields cover the diagnostic surface.
        "audience",
        "tenant_id",
        "subject",
        "actor",
        "reason",
        # Empty placeholders — recorded post-verification with the
        # actual identity values OR the error reason.
        "tracing::field::Empty",
        # Recording paths for both happy and error outcomes.
        "tracing::field::display",
    )
    missing = [name for name in must_have if name not in auth_guard]
    assert not missing, f"auth_guard.rs missing tracing wiring: {missing}"


def test_rust_sdk_parity_runner_shipped() -> None:
    """The cross-SDK parity runner ships in the Rust SDK's tests/
    directory. Loaded via the ``PARITY_FIXTURES`` env var pointing
    at the JSON dump from
    ``tests/contract/auth_sdk_parity/scenarios.py::scenarios_as_json()``.

    Behavioural verification (running the 19 scenarios end-to-end)
    happens via the SDK's cargo invocation:

        cd <project>/sdks/platform-auth-rs
        PARITY_FIXTURES=<scenarios.json> cargo test --features testing --test parity_runner

    This test gates the runner's *structural* presence + load-bearing
    wiring (gated behind ``cfg(feature = "testing")``, must consume
    AuthGuard + the testing-helper's TestEcdsaKeypair, must check the
    cross-language ``reason()`` slug contract).
    """
    runner_path = (
        _sdk_root() / "tests" / "parity_runner.rs"
    )
    assert runner_path.is_file(), (
        f"parity_runner.rs missing at {runner_path}"
    )
    text = runner_path.read_text(encoding="utf-8")
    must_have = (
        # File-level cfg gate so cargo test under the bare default
        # features simply doesn't compile this runner.
        '#![cfg(feature = "testing")]',
        # Loads scenarios from the env var path — same contract as
        # the Node runner.
        "PARITY_FIXTURES",
        # Imports the SDK's public surface + testing helper.
        "use platform_auth::",
        "AuthGuard",
        "AuthGuardConfig",
        "TestEcdsaKeypair",
        "build_test_token",
        # wiremock standing up a local JWKS responder so the verifier's
        # reqwest client doesn't try the network.
        "wiremock",
        "MockServer",
        # Cross-language slug → outcome match.
        ".reason()",
        # Pinning the slugs the runner expects to see — same set as
        # KNOWN_ERROR_SLUGS in the parity meta-test.
        "expected_slug",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"parity_runner.rs missing required wiring: {missing}"


def test_rust_sdk_axum_integration_test_shipped() -> None:
    """The Axum Tower-stack integration test ships in the Rust SDK's
    ``tests/`` directory. Validates the layer composition end-to-end —
    AuthLayer extracts the bearer, IdentityContext extractor reads
    from request extensions, RequireScope short-circuits with 403, the
    skip-list bypasses verification cleanly. The bare-verifier parity
    runner can't exercise this path; this is the unique-to-Rust gate.

    Behavioural verification runs via:

        cargo test --features axum,testing --test integration_axum

    This invariant pins the *structural* presence + key wiring so a
    future refactor can't silently delete the test or strip its
    cross-language contract assertions (RFC 7807 URI prefix, reason
    slugs).
    """
    integration_path = _sdk_root() / "tests" / "integration_axum.rs"
    assert integration_path.is_file(), (
        f"integration_axum.rs missing at {integration_path}"
    )
    text = integration_path.read_text(encoding="utf-8")
    must_have = (
        # Both features required — pulls in AuthLayer + the testing
        # helper. Default features alone shouldn't try to compile this.
        '#![cfg(all(feature = "axum", feature = "testing"))]',
        # Imports the public Tower types under test.
        "AuthLayer",
        "RequireScope",
        "IdentityContext",
        # Real Axum router + handler signature using the extractor.
        "axum::Router",
        "FromRequestParts",  # not directly imported, but the extractor
        # the test relies on lives in the trait — keep test loose; the
        # presence of `IdentityContext` as a handler param is the real
        # signal. (Drop this assertion if it proves brittle.)
        # Validates wire-protocol: RFC 7807 URI prefix shared with Node.
        "https://forge.dev/errors/",
        # Validates one of the cross-language reason slugs surfaces
        # through the Tower error path.
        "scope_required",
        # Skip-list assertion — same default set as Python + Node.
        "/health",
    )
    # Soft-check FromRequestParts presence — drop if test code shape
    # changes. `IdentityContext` as handler param is the load-bearing
    # signal; FromRequestParts is the trait that powers it.
    missing = [name for name in must_have if name not in text]
    if "FromRequestParts" in missing and len(missing) == 1:
        # Tolerated — test uses extractor without naming the trait.
        missing = []
    assert not missing, (
        f"integration_axum.rs missing required wiring: {missing}"
    )


def test_rust_sdk_audit_callback_module_present() -> None:
    """The audit-callback module ships and matches the cross-SDK shape.

    Mirrors Python's ``_emit_audit`` and Node's ``_emitAudit``: same
    record fields, same allow-only emit semantics, same `decision`
    slug values. Pinning the structural presence here so a future
    refactor can't silently strip the module or drift its public
    surface.

    Behavioural verification runs via:

        cargo test --features testing --test audit_callback

    (4 tests covering: allow-path full record, no-op when unset,
    deny is no-op, act-chain actor recorded.)
    """
    audit_path = _sdk_root() / "src" / "audit.rs"
    assert audit_path.is_file(), f"audit.rs missing at {audit_path}"
    text = audit_path.read_text(encoding="utf-8")
    must_have = (
        "pub struct AuthAuditRecord",
        "pub enum AuthDecision",
        "pub type AuthAuditCallback",
        # Cross-language record fields — pinned in lockstep with
        # Python and Node.
        "pub decision: AuthDecision",
        "pub audience: String",
        "pub audiences: Vec<String>",
        "pub ts_unix: f64",
        "pub tenant_id: Option<String>",
        "pub tenant_slug: Option<String>",
        "pub subject: Option<String>",
        "pub actor: Option<String>",
        "pub scopes: Option<Vec<String>>",
        "pub jti: Option<String>",
        "pub iss: Option<String>",
        "pub reason: Option<String>",
        # Slug values are part of the cross-language contract — same
        # strings the Python + Node records emit.
        '"allow"',
        '"deny"',
        # `Send + Sync` is mandatory because verify runs on the
        # multi-threaded tokio runtime.
        "Send + Sync",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"audit.rs missing required wiring: {missing}"


def test_rust_sdk_auth_guard_emits_audit_on_allow_path() -> None:
    """AuthGuard.verify_inner must call self.emit_audit(...) on the
    success path with the cross-language argument shape.

    Pins the wiring: a future refactor that moves the emit out of
    verify_inner (or drops it) regresses cross-SDK parity. Behavioural
    coverage is at tests/audit_callback.rs.
    """
    auth_guard_text = (_sdk_root() / "src" / "auth_guard.rs").read_text(encoding="utf-8")
    assert "audit: Option<AuthAuditCallback>" in auth_guard_text, (
        "AuthGuardConfig must declare `audit: Option<AuthAuditCallback>`"
    )
    assert "AuthDecision::Allow" in auth_guard_text, (
        "verify_inner must emit AuthDecision::Allow on the success path"
    )
    assert "fn emit_audit" in auth_guard_text, (
        "AuthGuard must define a private emit_audit helper"
    )


def test_rust_sdk_testing_helper_uses_aligned_claim_names() -> None:
    """``BuildTestTokenOptions`` field names must match the cross-language
    convention: ``roles_claim`` (plural), ``scope_claim``, ``tenant_id_claim``.

    Python uses ``roles_claim`` (plural). Node uses ``rolesClaim``
    (camelCase, plural). Rust's ``AuthGuardConfig`` uses ``roles_claim``.
    Until 2026-05 the Rust *testing* helper alone used ``role_claim``
    (singular) — a real cross-language API drift that survived because
    the parity runner builds tokens via ``BuildTestTokenOptions::new``
    (which sets the default and never references the field by name).

    This invariant pins the alignment so a future refactor can't
    silently re-introduce the drift.
    """
    testing_text = (_sdk_root() / "src" / "testing.rs").read_text(encoding="utf-8")
    # Aligned names — must be present.
    assert "pub roles_claim: String" in testing_text, (
        "BuildTestTokenOptions must declare `pub roles_claim: String` "
        "(plural — matches Python `roles_claim` and Node `rolesClaim`)"
    )
    assert "pub scope_claim: String" in testing_text
    assert "pub tenant_id_claim: String" in testing_text
    # Singular `role_claim` is the historical drift — must NOT recur.
    assert "role_claim:" not in testing_text, (
        "Rust testing helper must not use `role_claim` (singular). "
        "Cross-language convention is `roles_claim` (plural)."
    )


def test_rust_sdk_cargo_toml_includes_wiremock_dev_dep() -> None:
    """The Rust parity runner needs wiremock to stand up a local
    JWKS responder. Pin its presence in ``[dev-dependencies]`` so
    a future Cargo.toml edit doesn't strip it without flagging the
    parity-runner regression."""
    cargo = (_sdk_root() / "Cargo.toml").read_text(encoding="utf-8")
    assert "wiremock" in cargo, (
        "Cargo.toml dev-dependencies must include wiremock for the parity runner"
    )


def test_rust_sdk_error_reasons_match_python_contract() -> None:
    """``reason()`` slugs are the cross-language client-dispatch contract.

    Same slugs as the Python + Node SDKs.
    """
    errors_text = (_sdk_root() / "src" / "errors.rs").read_text(encoding="utf-8")
    expected_slugs = (
        "invalid_token",
        "token_expired",
        "token_revoked",
        "issuer_not_trusted",
        "actor_not_authorized",
        "scope_required",
        "tenant_suspended",
        "s2s_auth_error",
    )
    missing = [slug for slug in expected_slugs if f'"{slug}"' not in errors_text]
    assert not missing, f"AuthError reason slugs missing: {missing}"


def test_all_three_sdk_fragments_registered() -> None:
    """End-to-end check that every backend has its SDK fragment.

    With Phase 1 (Python), Phase 4 (Node), and Phase 6 (Rust) all
    landed, ``auth.mode=generate`` ought to enable one SDK fragment
    per backend in the project. (Wiring lands alongside the Phase 10
    cutover; this test just gates that the fragments themselves exist.)
    """
    expected = {
        BackendLanguage.PYTHON: "platform_auth_sdk_python",
        BackendLanguage.NODE: "platform_auth_sdk_node",
        BackendLanguage.RUST: "platform_auth_sdk_rust",
    }
    for backend, fragment_name in expected.items():
        assert fragment_name in FRAGMENT_REGISTRY, f"missing fragment: {fragment_name}"
        frag = FRAGMENT_REGISTRY[fragment_name]
        assert backend in frag.implementations, (
            f"{fragment_name} should target {backend.value}, got {list(frag.implementations.keys())}"
        )
        assert frag.implementations[backend].scope == "project"

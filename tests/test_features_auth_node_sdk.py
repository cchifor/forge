"""Invariants for the ``forge.features.auth`` Node SDK fragment (Phase 4).

Verifies that ``@forge/platform-auth-node`` (greenfield Node port of
the Python platform-auth SDK) is shipped with the public-surface
modules required for cross-language parity with the Python SDK.

Behavioural verification (the actual JWT verification, scope matching,
etc.) lives in the cross-SDK parity test suite at
``tests/contract/auth_sdk_parity/`` once Phase 9 lands.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 4 deliverables; cross-SDK parity gate at Phase 9).
"""

from __future__ import annotations

import json
from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


# Source modules that mirror the Python SDK's public surface. Any
# divergence here is a parity-breaking change and the cross-SDK parity
# fixtures will catch it at Phase 9.
PUBLIC_SDK_MODULES = (
    "AuthGuard.ts",
    "IdentityContext.ts",
    "JWKSCache.ts",
    "S2SClient.ts",
    "context.ts",
    "exceptions.ts",
    "may_act.ts",
    "middleware.ts",
    "plugin.ts",
    "revocation.ts",
    "scopes.ts",
    "trust.ts",
    "testing.ts",
    "index.ts",
)


# Sub-modules deliberately deferred to follow-up sub-phases.
# All Phase 4 follow-ups have now landed; this list documents that
# the SDK has reached structural parity with the Python and Rust
# ports.
DEFERRED_MODULES: tuple[str, ...] = ()


def _sdk_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_sdk_node"]
    impl = frag.implementations[BackendLanguage.NODE]
    return Path(impl.fragment_dir) / "files" / "sdks" / "platform-auth-node"


def test_platform_auth_sdk_node_fragment_registered() -> None:
    assert "platform_auth_sdk_node" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_sdk_node"]
    # Node-only — Phases 1 (Python) and 6 (Rust) are separate fragments.
    assert BackendLanguage.NODE in frag.implementations
    assert BackendLanguage.PYTHON not in frag.implementations
    assert BackendLanguage.RUST not in frag.implementations
    impl = frag.implementations[BackendLanguage.NODE]
    assert impl.scope == "project"
    # Auto-derived to tier 2 (Node-only). Promoted to tier 1 when Phase 6
    # lands the Rust SDK.
    assert frag.parity_tier == 2


def test_node_sdk_public_modules_present() -> None:
    """Every cross-language public surface module ships in the fragment."""
    src_dir = _sdk_root() / "src"
    assert src_dir.is_dir(), f"src/ tree missing: {src_dir}"
    shipped = {p.name for p in src_dir.glob("*.ts")}
    missing = set(PUBLIC_SDK_MODULES) - shipped
    assert not missing, f"public Node SDK modules not shipped: {sorted(missing)}"


def test_node_sdk_deferred_modules_documented() -> None:
    """The deferred-modules list is accurate — every entry is genuinely absent.

    A module showing up in PUBLIC_SDK_MODULES *and* in DEFERRED_MODULES
    is a contradiction; this test guards against silently flipping a
    deferred module to public without updating the test's expectation.
    """
    overlap = set(PUBLIC_SDK_MODULES) & set(DEFERRED_MODULES)
    assert not overlap, f"modules listed both public and deferred: {overlap}"

    src_dir = _sdk_root() / "src"
    shipped = {p.name for p in src_dir.glob("*.ts")}
    accidentally_shipped = set(DEFERRED_MODULES) & shipped
    assert not accidentally_shipped, (
        f"deferred modules unexpectedly present in src/: {sorted(accidentally_shipped)}. "
        "Update DEFERRED_MODULES + PUBLIC_SDK_MODULES if these are now ready."
    )


def test_node_sdk_package_json_shape() -> None:
    """The package.json declares ESM-native, public package metadata."""
    pkg_path = _sdk_root() / "package.json"
    assert pkg_path.is_file()
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    assert pkg["name"] == "@forge/platform-auth-node"
    assert pkg["type"] == "module", "SDK must be ESM-native"
    # jose is the load-bearing dependency for JWT verification + JWKS.
    assert "jose" in pkg["dependencies"], "package.json must depend on jose"
    # fastify-plugin powers the Fastify plugin's encapsulation-aware
    # decoration (Phase 4 follow-up). Without it, the request decoration
    # would not propagate to the parent application's routes.
    assert "fastify-plugin" in pkg["dependencies"], (
        "package.json must depend on fastify-plugin for the Fastify integration"
    )
    # peerDependencies on fastify keep the SDK usable outside Fastify
    # (e.g., from a CLI verifier or an event-bus consumer).
    assert "fastify" in pkg["peerDependencies"], (
        "fastify must be a peer dependency, not a hard dependency"
    )
    # Engines pin matches forge's CI matrix.
    assert pkg["engines"]["node"] == ">=20"


def test_node_sdk_tsconfig_shape() -> None:
    """tsconfig matches forge's Node convention (NodeNext ESM, strict)."""
    tsconfig_path = _sdk_root() / "tsconfig.json"
    assert tsconfig_path.is_file()
    text = tsconfig_path.read_text(encoding="utf-8")
    # Spot-check the load-bearing options.
    assert '"target": "ES2022"' in text
    assert '"module": "NodeNext"' in text
    assert '"strict": true' in text


def test_node_sdk_index_re_exports_public_surface() -> None:
    """index.ts must re-export every public symbol the parity tests expect.

    The parity-test suite imports from the package root, so any
    public-surface symbol missing from index.ts is invisible to
    consumers and the cross-language assertions can't run.
    """
    index_text = (_sdk_root() / "src" / "index.ts").read_text(encoding="utf-8")
    must_export = (
        "AuthGuard",
        "buildIdentity",
        "JWKSCache",
        "AuthError",
        "InvalidToken",
        "TokenExpired",
        "TokenRevoked",
        "IssuerNotTrusted",
        "ActorNotAuthorized",
        "ScopeRequired",
        "TenantSuspended",
        "S2SAuthError",
        "AllowAllMayActPolicy",
        "StaticMayActPolicy",
        "InMemoryIssuerTrustMap",
        "CachingIssuerTrustMap",
        "InMemoryRevocationStore",
        "NeverRevokedStore",
        "scopeSatisfies",
        "requireScope",
        "PLATFORM_SUPPORT_READ",
        "PLATFORM_SUPPORT_WRITE",
        "platformAuthPlugin",
        "DEFAULT_EXCLUDED_PATHS",
        "S2SClient",
        "DEFAULT_SAFETY_MARGIN_SECONDS",
        "identityContext",
        "runWithIdentity",
        "requireIdentity",
        "createAuthMiddleware",
    )
    missing = [name for name in must_export if name not in index_text]
    assert not missing, f"index.ts not re-exporting: {missing}"


def test_node_sdk_default_tenant_claim_is_forge_namespaced() -> None:
    """AuthGuard's default tenant claim must be forge-namespaced.

    Mirrors the Python SDK's own port-time decision: forge users get
    ``https://forge/tenant_id``, NOT ``https://platform/tenant_id``.
    """
    auth_guard = (_sdk_root() / "src" / "AuthGuard.ts").read_text(encoding="utf-8")
    assert (
        '"https://forge/tenant_id"' in auth_guard
    ), "DEFAULT_TENANT_ID_CLAIM must be the forge-namespaced URL"
    assert (
        '"https://platform/tenant_id"' not in auth_guard
    ), "AuthGuard.ts still references the platform-namespaced tenant claim"


def test_node_sdk_algorithms_are_asymmetric_only() -> None:
    """Default algorithms must reject ``none`` and HS* — security gate.

    The constructor unconditionally rejects ``none`` regardless of
    config; this test pins the default tuple to ``["ES256"]`` so a
    future config change can't silently widen it.
    """
    auth_guard = (_sdk_root() / "src" / "AuthGuard.ts").read_text(encoding="utf-8")
    assert (
        'export const DEFAULT_ALGORITHMS = ["ES256"]' in auth_guard
    ), "DEFAULT_ALGORITHMS must be a single-element ES256 tuple"


def test_node_sdk_plugin_module_exposes_fastify_integration() -> None:
    """plugin.ts must expose `platformAuthPlugin` + the option type
    + the default skip-list.

    The plugin is the load-bearing Fastify integration — without it,
    Phase 5 service-template middleware can't wire to anything.
    """
    plugin_text = (_sdk_root() / "src" / "plugin.ts").read_text(encoding="utf-8")
    must_have = (
        "platformAuthPlugin",
        "PlatformAuthPluginOptions",
        "DEFAULT_EXCLUDED_PATHS",
        "fastifyPlugin",  # fastify-plugin wrapping for encapsulation-aware decoration
        "decorateRequest",
        "addHook",
        "onRequest",
    )
    missing = [name for name in must_have if name not in plugin_text]
    assert not missing, f"plugin.ts missing required exports/wiring: {missing}"


def test_node_sdk_plugin_skips_health_metrics_docs_paths() -> None:
    """Health/metrics/docs probes must skip auth — same skip-list
    as the Python middleware so probes work consistently across
    backends."""
    plugin_text = (_sdk_root() / "src" / "plugin.ts").read_text(encoding="utf-8")
    for path in ("/health", "/metrics", "/docs", "/openapi.json"):
        assert path in plugin_text, (
            f"plugin.ts must list {path} in DEFAULT_EXCLUDED_PATHS — "
            f"matches Python middleware's skip-list"
        )


def test_node_sdk_plugin_maps_auth_errors_to_rfc7807() -> None:
    """AuthErrors translate to RFC 7807 problem responses.

    Matches the cross-language contract: clients dispatch on
    `error.reason` (the slug) and observability dashboards index
    the problem-type URI.
    """
    plugin_text = (_sdk_root() / "src" / "plugin.ts").read_text(encoding="utf-8")
    # The problem-type URI shape — pin it as a contract.
    assert "https://forge.dev/errors/" in plugin_text, (
        "plugin.ts must use https://forge.dev/errors/<reason> as the "
        "RFC 7807 problem-type URI prefix"
    )
    assert "WWW-Authenticate" in plugin_text, (
        "plugin.ts must set WWW-Authenticate: Bearer on auth failures"
    )


def test_node_sdk_s2s_client_exposes_oauth2_grants() -> None:
    """S2SClient.ts must expose both OAuth2 grants Gatekeeper accepts:
    `client_credentials` (machine identity, no `sub`) and the RFC
    8693 token-exchange (on-behalf-of, preserves user identity with
    `act` chain).

    Cross-language parity with Python `platform_auth.s2s_client.S2SClient`
    is the whole point — the Node version must support the same two
    flows or backends doing S2S calls would differ in observable ways.
    """
    text = (_sdk_root() / "src" / "S2SClient.ts").read_text(encoding="utf-8")
    must_have = (
        "S2SClient",
        "client_credentials",
        # The RFC 8693 grant URI is part of the OAuth wire protocol —
        # any change is a parity break.
        "urn:ietf:params:oauth:grant-type:token-exchange",
        "urn:ietf:params:oauth:token-type:access_token",
        "subject_token",
        # Cache observability — services emit Prometheus gauges off
        # this surface.
        "cacheStats",
        # 401-retry-once behavior matches Python.
        "this.invalidate",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"S2SClient.ts missing required wiring: {missing}"


def test_node_sdk_s2s_client_caches_with_lru() -> None:
    """The cache uses lru-cache (declared dep). Bounded by
    `maxCacheEntries` so a long-lived process minting tokens for
    many distinct user `jti`s doesn't grow without bound.
    """
    text = (_sdk_root() / "src" / "S2SClient.ts").read_text(encoding="utf-8")
    assert "lru-cache" in text or "LRUCache" in text, (
        "S2SClient.ts must use lru-cache for bounded token caching"
    )
    assert "maxCacheEntries" in text, (
        "S2SClient.ts must accept maxCacheEntries as a config knob"
    )


def test_node_sdk_s2s_client_safety_margin_default() -> None:
    """60-second pre-expiry refresh matches Python's default."""
    text = (_sdk_root() / "src" / "S2SClient.ts").read_text(encoding="utf-8")
    assert "DEFAULT_SAFETY_MARGIN_SECONDS = 60" in text, (
        "DEFAULT_SAFETY_MARGIN_SECONDS must be 60 to match Python's default"
    )


def test_node_sdk_testing_module_exposes_token_minter() -> None:
    """testing.ts must expose the parity-fixture API surface.

    The cross-SDK parity gate (Phase 9) needs ``buildTestToken`` and
    a generator for ECDSA P-256 keypairs. Both Node and Rust SDKs
    must expose equivalents so a fixture authored once can be
    regenerated in any language.
    """
    src_dir = _sdk_root() / "src"
    testing_text = (src_dir / "testing.ts").read_text(encoding="utf-8")
    must_have = (
        "buildTestToken",
        "TestEcdsaKeypair",
        "generateTestKeypair",
        "ES256",
        "exportJWK",
        "SignJWT",
    )
    missing = [name for name in must_have if name not in testing_text]
    assert not missing, f"testing.ts missing required exports: {missing}"


def test_node_sdk_testing_uses_forge_namespaced_default_claim() -> None:
    """buildTestToken must default to ``https://forge/tenant_id``.

    Same forge-namespacing decision as AuthGuard's defaults — the
    helper and the verifier must agree on the default claim name
    or test tokens won't verify out-of-the-box.
    """
    testing_text = (_sdk_root() / "src" / "testing.ts").read_text(encoding="utf-8")
    assert (
        '"https://forge/tenant_id"' in testing_text
    ), "buildTestToken must default the tenant_id claim to https://forge/tenant_id"


def test_node_sdk_testing_helper_uses_aligned_claim_names() -> None:
    """``BuildTestTokenOptions`` field names must match the cross-language
    convention: ``rolesClaim`` (plural camelCase), ``scopeClaim``,
    ``tenantIdClaim``.

    Python uses ``roles_claim`` (plural snake_case). Rust's
    ``BuildTestTokenOptions`` uses ``roles_claim``. Node's ``AuthGuard``
    config field is ``rolesClaim``. Until 2026-05 the Node *testing*
    helper alone used ``roleClaim`` (singular) — a real cross-language
    API drift that survived because the parity runner never sets the
    field by name.

    This invariant pins the alignment so a future refactor can't
    silently re-introduce the drift.
    """
    testing_text = (_sdk_root() / "src" / "testing.ts").read_text(encoding="utf-8")
    # Aligned name — must be present.
    assert "rolesClaim?: string" in testing_text, (
        "BuildTestTokenOptions must declare `rolesClaim?: string` "
        "(plural — matches AuthGuardConfig.rolesClaim, "
        "Python `roles_claim`, Rust `roles_claim`)"
    )
    # Singular `roleClaim` is the historical drift — must NOT recur.
    assert "roleClaim?:" not in testing_text, (
        "Node testing helper must not use `roleClaim` (singular). "
        "Cross-language convention is `rolesClaim` (plural)."
    )
    assert "opts.roleClaim" not in testing_text, (
        "Node testing helper body must not reference `opts.roleClaim` (singular)."
    )


def test_node_sdk_context_uses_async_local_storage() -> None:
    """context.ts must use Node's `AsyncLocalStorage` for cross-async-
    boundary identity propagation. Mirrors Python's `ContextVar`
    semantics — without it, background tasks (queue consumers, timer
    callbacks) lose tenant context after the request handler returns.
    """
    text = (_sdk_root() / "src" / "context.ts").read_text(encoding="utf-8")
    must_have = (
        "AsyncLocalStorage",
        "node:async_hooks",
        "identityContext",
        "runWithIdentity",
        "getCurrentIdentity",
        "requireIdentity",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"context.ts missing required exports: {missing}"


def test_node_sdk_middleware_factory_present() -> None:
    """middleware.ts must export `createAuthMiddleware` — the
    framework-agnostic onRequest factory used by tests + non-Fastify
    HTTP frameworks. Returns a typed result discriminator (`verified`
    / `excluded` / `rejected`) so callers map to their framework's
    response shape without exception-throwing for the rejected case.
    """
    text = (_sdk_root() / "src" / "middleware.ts").read_text(encoding="utf-8")
    must_have = (
        "createAuthMiddleware",
        "AuthMiddlewareResult",
        # Three-arm discriminator.
        '"verified"',
        '"excluded"',
        '"rejected"',
        # Honors the same skip-list as the Fastify plugin.
        "DEFAULT_EXCLUDED_PATHS",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"middleware.ts missing required wiring: {missing}"


def test_node_sdk_parity_runner_shipped() -> None:
    """The cross-SDK parity runner ships in the Node SDK's test/
    directory. Loaded via the ``PARITY_FIXTURES`` env var pointing
    at the JSON dump from
    ``tests/contract/auth_sdk_parity/scenarios.py::scenarios_as_json()``.

    Behavioural verification (running the 19 scenarios end-to-end)
    happens via the SDK's vitest invocation:

        cd <project>/sdks/platform-auth-node
        npm install
        PARITY_FIXTURES=<scenarios.json> npx vitest run test/parity_runner.test.ts

    This test gates the runner's *structural* presence + load-bearing
    wiring (must import from `../src/index.js`, must consume
    `buildTestToken` + `generateTestKeypair`, must check the cross-
    language `reason()` slug contract).
    """
    runner_path = _sdk_root() / "test" / "parity_runner.test.ts"
    assert runner_path.is_file(), (
        f"parity_runner.test.ts missing at {runner_path}"
    )
    text = runner_path.read_text(encoding="utf-8")
    must_have = (
        # Loads scenarios from the env var path.
        "PARITY_FIXTURES",
        # Imports the SDK's public surface.
        '../src/index.js',
        # Imports the testing helper.
        '../src/testing.js',
        "buildTestToken",
        "generateTestKeypair",
        # vitest test framework.
        "from \"vitest\"",
        "describe",
        # Slug → constructor map (cross-language reason() contract).
        "SLUG_TO_CTOR",
        "invalid_token",
        "token_expired",
        "token_revoked",
        "issuer_not_trusted",
        "actor_not_authorized",
        "scope_required",
        "tenant_suspended",
        # Asserts the AuthError.reason slug pins to the cross-language
        # contract.
        ".reason",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, f"parity_runner.test.ts missing required wiring: {missing}"


def test_node_sdk_audit_callback_shape_matches_cross_sdk_contract() -> None:
    """``AuthAuditRecord`` shape pins the cross-language audit contract.

    Same fields as Python's ``_emit_audit`` record dict and Rust's
    ``AuthAuditRecord`` struct. Downstream pipelines treat the shape
    as the public contract — drift one field name and consumers break
    silently.

    The Node SDK is the canonical reference for camelCase naming;
    Python uses snake_case (``tenant_id``, ``ts_unix``) and Rust uses
    snake_case + Option types (``tenant_id: Option<String>``). Field
    presence + types pinned here so all three stay aligned.
    """
    auth_guard_text = (
        _sdk_root() / "src" / "AuthGuard.ts"
    ).read_text(encoding="utf-8")
    must_have = (
        "export type AuthAuditRecord",
        "export type AuthAuditCallback",
        # Cross-language record fields.
        'decision: "allow" | "deny"',
        "audience: string",
        "audiences: readonly string[]",
        "tsUnix: number",
        "tenantId?: string",
        "tenantSlug?: string | null",
        "subject?: string",
        "actor?: string | null",
        "scopes?: readonly string[]",
        "jti?: string",
        "iss?: string",
        "reason?: string",
        # AuthGuardConfig must expose the optional callback.
        "audit?: AuthAuditCallback",
    )
    missing = [name for name in must_have if name not in auth_guard_text]
    assert not missing, (
        f"AuthGuard.ts missing audit-callback wiring: {missing}"
    )


def test_node_sdk_audit_callback_test_shipped() -> None:
    """The Node SDK's dedicated audit-callback test file ships in the
    template tree. Mirrors the Rust ``tests/audit_callback.rs`` cargo
    test and Python's ``TestAudit`` class in
    ``tests/unit/test_auth_guard.py``.

    Behavioural verification runs via:

        cd <project>/sdks/platform-auth-node
        npx vitest run test/audit_callback.test.ts

    Pinning the structural presence here so a future template refactor
    can't silently drop the test or strip its cross-language contract
    assertions (record-shape, tenant_slug propagation, deny-no-op).
    """
    test_path = _sdk_root() / "test" / "audit_callback.test.ts"
    assert test_path.is_file(), (
        f"audit_callback.test.ts missing at {test_path}"
    )
    text = test_path.read_text(encoding="utf-8")
    must_have = (
        # Imports the SDK's public surface + testing helper.
        "AuthGuard",
        "AuthAuditRecord",
        "buildTestToken",
        "generateTestKeypair",
        # Cross-language record-shape assertions.
        '"allow"',
        "tenantId",
        "tenantSlug",
        "tsUnix",
        # The 4 named tests pinning the contract.
        "fires once on the allow path",
        "propagates tenant_slug",
        "tenant_slug is null when the claim is absent",
        "does not fire on the deny path",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, (
        f"audit_callback.test.ts missing required wiring: {missing}"
    )


def test_node_sdk_emit_audit_fires_only_on_allow_path() -> None:
    """The Node ``_emitAudit`` call must only fire from the allow path.

    Today's cross-SDK contract: Python + Node + Rust all emit on
    allow only; deny is reserved as a forward-compat extension point.
    Pinning the call site count here so a future refactor that adds
    deny-path emit lands in lockstep across all three SDKs.
    """
    auth_guard_text = (
        _sdk_root() / "src" / "AuthGuard.ts"
    ).read_text(encoding="utf-8")
    # Only one call site: the success path emits with `decision: "allow"`.
    allow_emit_count = auth_guard_text.count('_emitAudit({ decision: "allow"')
    assert allow_emit_count == 1, (
        f"expected exactly 1 allow-path _emitAudit call, found {allow_emit_count}"
    )
    deny_emit_count = auth_guard_text.count('_emitAudit({ decision: "deny"')
    assert deny_emit_count == 0, (
        "deny-path _emitAudit is reserved for forward-compat parity; "
        "Python + Rust currently don't emit on deny either"
    )


def test_node_sdk_exception_reasons_match_python_contract() -> None:
    """``reason`` slugs are the cross-language client-dispatch contract.

    Changing one is a breaking change for every client that maps
    reasons to UI strings / metrics labels. This test pins the slugs
    to match the Python SDK byte-for-byte.
    """
    exc_text = (_sdk_root() / "src" / "exceptions.ts").read_text(encoding="utf-8")
    # Each entry: the literal slug must appear in exceptions.ts on the
    # corresponding subclass. Slugs are snake_case so they're stable
    # across language conventions.
    expected_slugs = (
        "auth_error",
        "invalid_token",
        "token_expired",
        "token_revoked",
        "issuer_not_trusted",
        "actor_not_authorized",
        "scope_required",
        "tenant_suspended",
        "s2s_auth_error",
    )
    missing = [slug for slug in expected_slugs if f'"{slug}"' not in exc_text]
    assert not missing, f"exception reason slugs missing: {missing}"

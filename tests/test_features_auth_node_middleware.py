"""Invariants for the Node service-template middleware fragment (Phase 5).

The fragment ships per-Node-backend service modules wiring the
``@forge/platform-auth-node`` SDK into Fastify's lifecycle. Mirrors
Phase 3 (Python middleware) in TypeScript / Fastify idioms.

Behavioural verification (the actual plugin running, request decoration,
RFC 7807 error responses) lives in the cross-SDK parity gate (Phase 9)
and the e2e auth chain test. This file gates the *structural* presence
of the modules + their key load-bearing wiring.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 5 deliverables).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


EXPECTED_FILES = (
    "src/middleware/auth.ts",
    "src/types/auth.ts",
)


def _fragment_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_node_middleware"]
    impl = frag.implementations[BackendLanguage.NODE]
    return Path(impl.fragment_dir)


def _files_root() -> Path:
    return _fragment_root() / "files"


def test_node_middleware_fragment_registered() -> None:
    assert "platform_auth_node_middleware" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_node_middleware"]
    # Node-only.
    assert BackendLanguage.NODE in frag.implementations
    assert BackendLanguage.PYTHON not in frag.implementations
    assert BackendLanguage.RUST not in frag.implementations
    impl = frag.implementations[BackendLanguage.NODE]
    # Backend-scoped — files land per-backend.
    assert impl.scope == "backend"


def test_node_middleware_depends_on_sdk() -> None:
    """The middleware imports ``from @forge/platform-auth-node``.
    Without the SDK fragment, the workspace dependency wouldn't
    resolve.
    """
    frag = FRAGMENT_REGISTRY["platform_auth_node_middleware"]
    assert "platform_auth_sdk_node" in frag.depends_on, (
        "platform_auth_node_middleware must depend on the SDK fragment"
    )


def test_node_middleware_workspace_dep_declared() -> None:
    """The fragment declares the workspace dep so it lands in the
    consuming service's package.json automatically.
    """
    frag = FRAGMENT_REGISTRY["platform_auth_node_middleware"]
    impl = frag.implementations[BackendLanguage.NODE]
    deps = impl.dependencies
    assert any("@forge/platform-auth-node" in d for d in deps), (
        f"fragment must declare @forge/platform-auth-node as a dependency; got {deps}"
    )


def test_node_middleware_files_shipped() -> None:
    """All expected files must land at the conventional Fastify-service paths."""
    root = _files_root()
    for relative in EXPECTED_FILES:
        path = root / relative
        assert path.is_file(), f"missing fragment file: {relative} (at {path})"


def test_auth_bootstrap_uses_sdk_plugin() -> None:
    """The bootstrap module must register the SDK's plugin and
    construct an AuthGuard from environment-driven config.
    """
    text = (_files_root() / "src" / "middleware" / "auth.ts").read_text(encoding="utf-8")
    must_reference = (
        "platformAuthPlugin",
        "AuthGuard",
        "JWKSCache",
        "GATEKEEPER_ISSUER",
        "SERVICE_AUDIENCE",
        "/auth/jwks",
        "@forge/platform-auth-node",
    )
    missing = [name for name in must_reference if name not in text]
    assert not missing, (
        f"middleware/auth.ts missing required wiring: {missing}"
    )


def test_auth_bootstrap_default_tenant_claim_is_forge_namespaced() -> None:
    """Same forge-namespacing decision as the SDK's defaults."""
    text = (_files_root() / "src" / "middleware" / "auth.ts").read_text(encoding="utf-8")
    assert "https://forge/tenant_id" in text, (
        "bootstrapAuth must default tenantIdClaim to https://forge/tenant_id"
    )


def test_auth_bootstrap_pins_es256() -> None:
    """ES256 only — same algorithm-pin contract as the SDK defaults."""
    text = (_files_root() / "src" / "middleware" / "auth.ts").read_text(encoding="utf-8")
    assert '"ES256"' in text, "bootstrapAuth must pin algorithms to ES256"


def test_types_auth_re_exports_identity_context() -> None:
    """``src/types/auth.ts`` must re-export the SDK's IdentityContext
    + the narrowed AuthenticatedRequest type so handlers don't
    couple to the SDK's package name.
    """
    text = (_files_root() / "src" / "types" / "auth.ts").read_text(encoding="utf-8")
    assert "IdentityContext" in text, "types/auth.ts must re-export IdentityContext"
    assert "AuthenticatedRequest" in text, (
        "types/auth.ts must define AuthenticatedRequest for handler signatures"
    )
    assert "@forge/platform-auth-node" in text, (
        "types/auth.ts must import from @forge/platform-auth-node"
    )


def test_inject_yaml_wires_app_ts_markers() -> None:
    """The ``inject.yaml`` adds the import + bootstrap call to
    ``src/app.ts`` at the canonical FORGE markers — same convention
    as security_headers / rate_limit Node fragments.
    """
    inject_path = _fragment_root() / "inject.yaml"
    assert inject_path.is_file(), f"inject.yaml missing at {inject_path}"
    blocks = yaml.safe_load(inject_path.read_text(encoding="utf-8"))
    assert isinstance(blocks, list) and len(blocks) >= 2, (
        "inject.yaml must declare at least two injections (import + register)"
    )
    targets = {b["target"] for b in blocks}
    markers = {b["marker"] for b in blocks}
    snippets = " ".join(b["snippet"] for b in blocks)
    assert "src/app.ts" in targets, "inject.yaml must target src/app.ts"
    assert "FORGE:MIDDLEWARE_IMPORTS" in markers, (
        "inject.yaml must use the FORGE:MIDDLEWARE_IMPORTS marker for the import"
    )
    assert "FORGE:MIDDLEWARE_REGISTRATION" in markers, (
        "inject.yaml must use the FORGE:MIDDLEWARE_REGISTRATION marker for app.register"
    )
    assert "bootstrapAuth(app)" in snippets, (
        "inject.yaml must call bootstrapAuth(app) at MIDDLEWARE_REGISTRATION"
    )


def test_node_middleware_fragment_not_yet_wired_to_auth_mode() -> None:
    """Phase 5's fragment registered but NOT yet wired into
    ``auth.mode=generate``'s enables map. Conflict-with-legacy
    concern same as Phase 3 — bundled with the atomic cutover."""
    from forge.options import OPTION_REGISTRY

    auth_mode = OPTION_REGISTRY["auth.mode"]
    enabled = auth_mode.enables.get("generate", ())
    assert "platform_auth_node_middleware" not in enabled, (
        "platform_auth_node_middleware was wired before the Phase 2 cutover"
    )

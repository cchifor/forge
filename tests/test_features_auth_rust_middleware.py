"""Invariants for the Rust service-template middleware fragment (Phase 7).

The fragment ships per-Rust-backend service modules wiring the
`platform-auth` Rust SDK into Axum's lifecycle. Mirrors Phase 3
(Python middleware) and Phase 5 (Node middleware) in Rust /
Tower idioms — ``axum::middleware::from_fn``-compatible verifier
+ ``OnceLock``-based shared AuthGuard state.

Behavioural verification (the actual middleware running, request-
extension binding, RFC 7807 error responses) lives in the cross-
SDK parity gate (Phase 9) and the e2e auth chain test. This file
gates the *structural* presence of the modules + their key
load-bearing wiring.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 7 deliverables).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


EXPECTED_FILES = (
    "src/middleware/auth.rs",
)


def _fragment_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_rust_middleware"]
    impl = frag.implementations[BackendLanguage.RUST]
    return Path(impl.fragment_dir)


def _files_root() -> Path:
    return _fragment_root() / "files"


def test_rust_middleware_fragment_registered() -> None:
    assert "platform_auth_rust_middleware" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_rust_middleware"]
    assert BackendLanguage.RUST in frag.implementations
    assert BackendLanguage.PYTHON not in frag.implementations
    assert BackendLanguage.NODE not in frag.implementations
    impl = frag.implementations[BackendLanguage.RUST]
    assert impl.scope == "backend"


def test_rust_middleware_depends_on_sdk() -> None:
    """The middleware imports `platform_auth::*`. Without the SDK
    fragment, the path-dep wouldn't resolve at the consuming Cargo.toml.
    """
    frag = FRAGMENT_REGISTRY["platform_auth_rust_middleware"]
    assert "platform_auth_sdk_rust" in frag.depends_on, (
        "platform_auth_rust_middleware must depend on the SDK fragment"
    )


def test_rust_middleware_path_dep_declared() -> None:
    """The fragment declares the path-dep so it lands in the consuming
    service's Cargo.toml automatically."""
    frag = FRAGMENT_REGISTRY["platform_auth_rust_middleware"]
    impl = frag.implementations[BackendLanguage.RUST]
    deps = impl.dependencies
    assert any("platform-auth" in d and "../sdks/platform-auth-rs" in d for d in deps), (
        f"fragment must declare platform-auth as a path-dep against "
        f"../sdks/platform-auth-rs; got {deps}"
    )


def test_rust_middleware_files_shipped() -> None:
    root = _files_root()
    for relative in EXPECTED_FILES:
        path = root / relative
        assert path.is_file(), f"missing fragment file: {relative} (at {path})"


def test_auth_middleware_uses_sdk() -> None:
    """The middleware module must construct AuthGuard + JwksCache
    from the SDK's primitives."""
    text = (_files_root() / "src" / "middleware" / "auth.rs").read_text(encoding="utf-8")
    must_reference = (
        "use platform_auth::",
        "AuthGuard",
        "JwksCache",
        "GATEKEEPER_ISSUER",
        "SERVICE_AUDIENCE",
        "/auth/jwks",
    )
    missing = [name for name in must_reference if name not in text]
    assert not missing, f"middleware/auth.rs missing required wiring: {missing}"


def test_auth_middleware_skips_health_metrics_paths() -> None:
    """Same skip-list as the Python middleware and Node plugin —
    cross-language behavior must be identical."""
    text = (_files_root() / "src" / "middleware" / "auth.rs").read_text(encoding="utf-8")
    for path in ("/health", "/metrics", "/docs", "/openapi.json"):
        assert path in text, (
            f"middleware/auth.rs must list {path} in EXCLUDED_PATHS — "
            f"matches Python + Node skip-list"
        )


def test_auth_middleware_default_tenant_claim_is_forge_namespaced() -> None:
    text = (_files_root() / "src" / "middleware" / "auth.rs").read_text(encoding="utf-8")
    # Defaults to TENANT_ID_CLAIM env var, falling back to the SDK's
    # default (which is forge-namespaced). Either explicit reference is
    # acceptable — pin via the SDK's reliance.
    assert "TENANT_ID_CLAIM" in text, (
        "middleware/auth.rs must read TENANT_ID_CLAIM env override (defaults "
        "to https://forge/tenant_id via the SDK)"
    )


def test_auth_middleware_uses_axum_from_fn_signature() -> None:
    """The middleware function must match axum::middleware::from_fn's
    expected signature so the inject.yaml wiring compiles.
    """
    text = (_files_root() / "src" / "middleware" / "auth.rs").read_text(encoding="utf-8")
    must_have = (
        "pub async fn auth_middleware",
        "Request<Body>",
        "Next",
        "Response",
    )
    missing = [name for name in must_have if name not in text]
    assert not missing, (
        f"middleware/auth.rs's auth_middleware must match axum::from_fn "
        f"signature: missing {missing}"
    )


def test_auth_middleware_init_auth_function_present() -> None:
    """Startup wiring: main() calls init_auth() before serving.
    Without it, the OnceLock is empty and every request fails 503."""
    text = (_files_root() / "src" / "middleware" / "auth.rs").read_text(encoding="utf-8")
    assert "pub async fn init_auth" in text, (
        "middleware/auth.rs must expose an init_auth() function for main() to call"
    )
    assert "OnceLock" in text, (
        "middleware/auth.rs must use OnceLock for the global AuthGuard "
        "(or document an alternative shared-state mechanism)"
    )


def test_auth_middleware_maps_errors_to_rfc7807() -> None:
    """AuthErrors translate to RFC 7807 problem responses with the
    same `https://forge.dev/errors/<reason>` URI prefix as the Node
    plugin uses — cross-language client dispatch contract."""
    text = (_files_root() / "src" / "middleware" / "auth.rs").read_text(encoding="utf-8")
    assert "https://forge.dev/errors/" in text, (
        "middleware/auth.rs must use https://forge.dev/errors/<reason> "
        "RFC 7807 problem-type URI prefix"
    )
    assert "WWW_AUTHENTICATE" in text or "WWW-Authenticate" in text, (
        "middleware/auth.rs must set WWW-Authenticate: Bearer on 401 responses"
    )


def test_inject_yaml_wires_module_and_layer() -> None:
    """The inject.yaml adds the `pub mod auth;` declaration to
    middleware/mod.rs AND the layer registration to app.rs."""
    inject_path = _fragment_root() / "inject.yaml"
    assert inject_path.is_file(), f"inject.yaml missing at {inject_path}"
    blocks = yaml.safe_load(inject_path.read_text(encoding="utf-8"))
    assert isinstance(blocks, list) and len(blocks) >= 3, (
        "inject.yaml must declare at least three injections "
        "(mod registration + import + layer)"
    )
    targets = {b["target"] for b in blocks}
    snippets = " ".join(b["snippet"] for b in blocks)

    assert "src/middleware/mod.rs" in targets, (
        "inject.yaml must register the auth submodule via middleware/mod.rs"
    )
    assert "src/app.rs" in targets, (
        "inject.yaml must wire the layer into src/app.rs"
    )
    assert "pub mod auth" in snippets, (
        "inject.yaml must declare `pub mod auth;` in middleware/mod.rs"
    )
    assert "axum::middleware::from_fn(auth_middleware)" in snippets, (
        "inject.yaml must add `.layer(axum::middleware::from_fn(auth_middleware))` "
        "to the app router"
    )


def test_rust_middleware_fragment_not_yet_wired_to_auth_mode() -> None:
    """Phase 7's fragment registered but NOT yet wired into
    ``auth.mode=generate``'s enables map. Conflict-with-legacy
    concern same as Phase 3 — bundled with the atomic cutover."""
    from forge.options import OPTION_REGISTRY

    auth_mode = OPTION_REGISTRY["auth.mode"]
    enabled = auth_mode.enables.get("generate", ())
    assert "platform_auth_rust_middleware" not in enabled, (
        "platform_auth_rust_middleware was wired before the Phase 2 cutover"
    )

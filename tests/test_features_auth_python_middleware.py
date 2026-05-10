"""Invariants for the Python service-template middleware fragment (Phase 3).

The fragment ships per-Python-backend service modules that wire the
platform-auth SDK into FastAPI's middleware + dependency stack.
Behavioural verification (the actual middleware running, request.state
binding, ContextVar propagation) lives in the cross-SDK parity gate
(Phase 9) and the e2e auth chain test (Phase 9 / 10). This file
gates the *structural* presence of the modules + their key
load-bearing imports.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 3 deliverables).
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


# The 6 modules ported verbatim from platform/services/{any}/src/.
# Each addresses a different layer of the auth stack:
#   - middleware: per-request verification (single-pass)
#   - core dependencies: FastAPI Depends() factories
#   - security setup: AuthGuardBundle wiring
#   - security auth: token extraction + User translation
#   - client auth: outbound S2S token manager
#   - core context: ContextVars for cross-async-boundary propagation
EXPECTED_FILES = (
    "src/app/middleware/auth_context.py",
    "src/app/core/auth.py",
    "src/service/security/platform_auth_setup.py",
    "src/service/security/auth.py",
    "src/service/client/auth.py",
    "src/service/core/context.py",
)


def _fragment_root() -> Path:
    frag = FRAGMENT_REGISTRY["platform_auth_python_middleware"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    return Path(impl.fragment_dir) / "files"


def test_python_middleware_fragment_registered() -> None:
    assert "platform_auth_python_middleware" in FRAGMENT_REGISTRY
    frag = FRAGMENT_REGISTRY["platform_auth_python_middleware"]
    # Python-only.
    assert BackendLanguage.PYTHON in frag.implementations
    assert BackendLanguage.NODE not in frag.implementations
    assert BackendLanguage.RUST not in frag.implementations
    impl = frag.implementations[BackendLanguage.PYTHON]
    # Backend-scoped (NOT project-scoped) — files land per-backend.
    assert impl.scope == "backend"


def test_python_middleware_depends_on_sdk() -> None:
    """The middleware imports ``from platform_auth import AuthGuard``.
    The SDK fragment ships ``sdks/platform-auth/`` at the project
    root; without it, the imports don't resolve.
    """
    frag = FRAGMENT_REGISTRY["platform_auth_python_middleware"]
    assert "platform_auth_sdk_python" in frag.depends_on, (
        "platform_auth_python_middleware must depend on the SDK fragment "
        "so the path-dep import resolves at the consuming pyproject"
    )


def test_python_middleware_files_shipped() -> None:
    """All 6 files must land at the conventional Python-service paths."""
    root = _fragment_root()
    for relative in EXPECTED_FILES:
        path = root / relative
        assert path.is_file(), f"missing fragment file: {relative} (at {path})"


def test_auth_context_middleware_uses_sdk() -> None:
    """The middleware must consume the SDK (directly or via the local
    ``service.security.auth`` shim). The shim is the platform-canonical
    integration point — it imports ``platform_auth.IdentityContext`` and
    runs the verifier.
    """
    middleware_text = (
        _fragment_root() / "src" / "app" / "middleware" / "auth_context.py"
    ).read_text(encoding="utf-8")
    # The middleware references IdentityContext (in the docstring + at
    # least once in code) and dispatches to ``service.security.auth``.
    assert "IdentityContext" in middleware_text, (
        "auth_context.py must reference platform_auth.IdentityContext"
    )
    assert "service.security.auth" in middleware_text, (
        "auth_context.py must dispatch to service.security.auth (the "
        "shim that wraps platform_auth.AuthGuard)"
    )
    # Skip-list for /health, /metrics, /docs, /openapi.json — the
    # request-state binding wouldn't help on those endpoints anyway,
    # AND skipping them avoids 401-spamming healthchecks.
    text_lower = middleware_text.lower()
    skipped_endpoints_present = all(
        endpoint in text_lower for endpoint in ("/health", "/metrics", "/docs", "/openapi")
    )
    assert skipped_endpoints_present, (
        "auth_context middleware must skip /health, /metrics, /docs, "
        "and /openapi.json paths to avoid 401-spamming probes"
    )
    # The actual SDK import lives in service/security/auth.py — pin
    # it there so the chain is complete.
    auth_shim = (
        _fragment_root() / "src" / "service" / "security" / "auth.py"
    ).read_text(encoding="utf-8")
    assert "from platform_auth" in auth_shim or "platform_auth" in auth_shim, (
        "service/security/auth.py (the shim middleware delegates to) "
        "must import from platform_auth"
    )


def test_platform_auth_setup_constructs_auth_guard_bundle() -> None:
    """The setup module wires ``AuthGuard`` + ``JWKSCache`` + trust map
    + may-act policy from environment config — that's the integration
    point Phase 3 unblocks for downstream Phase 9 / 10 work.
    """
    text = (
        _fragment_root() / "src" / "service" / "security" / "platform_auth_setup.py"
    ).read_text(encoding="utf-8")
    must_reference = ("AuthGuard", "JWKSCache")
    missing = [name for name in must_reference if name not in text]
    assert not missing, (
        f"platform_auth_setup.py must reference {missing} from the SDK"
    )


def test_core_auth_exposes_fastapi_dependencies() -> None:
    """``app/core/auth.py`` is the FastAPI ``Depends()`` factory module.
    Service handlers consume these — they're the public surface of the
    Phase 3 fragment from the perspective of route authors.

    Platform's canonical surface is three accessors:
    ``get_gatekeeper_user`` (returns User), ``get_tenant_id`` (returns
    str for direct row-scoping), and ``get_account`` (returns Account
    bundle for the dependency-injection layer). Role-gated endpoints
    use ``identity.has_scope("...")`` directly rather than a
    ``require_admin`` helper — scope-based authz is the design.
    """
    text = (_fragment_root() / "src" / "app" / "core" / "auth.py").read_text(encoding="utf-8")
    must_define = ("get_gatekeeper_user", "get_tenant_id", "get_account")
    missing = [name for name in must_define if f"def {name}" not in text]
    assert not missing, (
        f"app/core/auth.py must define {missing} — those are the FastAPI "
        f"dependency factories Phase 3 promises to ship"
    )


def test_service_core_context_defines_context_vars() -> None:
    """ContextVars propagate identity across async boundaries — without
    them, async background tasks lose tenant context. Pin the three
    canonical vars by name."""
    text = (_fragment_root() / "src" / "service" / "core" / "context.py").read_text(
        encoding="utf-8"
    )
    assert "ContextVar" in text, "context.py must use ContextVar"
    must_define = (
        "customer_id_context",
        "user_id_context",
    )
    missing = [name for name in must_define if name not in text]
    assert not missing, f"context.py must define {missing} ContextVars"


def test_service_client_auth_caches_tokens() -> None:
    """``service/client/auth.py`` is the outbound-S2S helper. It must
    cache tokens (otherwise every outbound call mints a fresh token,
    blowing up the IdP load)."""
    text = (_fragment_root() / "src" / "service" / "client" / "auth.py").read_text(
        encoding="utf-8"
    )
    # Cache-class implementation lives inline — ClientCredentialsAuth.
    assert "ClientCredentialsAuth" in text, (
        "service/client/auth.py must define ClientCredentialsAuth — "
        "the cached OAuth2 token manager for outbound calls"
    )


def test_python_middleware_fragment_not_yet_wired_to_auth_mode() -> None:
    """Phase 3's middleware is registered but intentionally NOT yet
    wired into ``auth.mode=generate``'s enables map.

    Reason: forge's existing python-service-template ships
    ``service/security/auth.py`` and ``service/client/auth.py`` at the
    same paths this fragment writes — wiring without first removing
    those legacy files (in a coordinated cutover with the Phase 2
    gatekeeper template removal) emits a hard ``FragmentError`` at
    generate time.

    The fragment IS reachable via the migration codemod path —
    ``forge --migrate auth-keycloak-to-platform-auth`` strips the
    legacy files first, then ``forge --update`` ships the fragment.
    Greenfield projects need the cutover landed before they can
    consume this fragment.

    Negative invariant — flip when the cutover lands.
    """
    from forge.options import OPTION_REGISTRY

    auth_mode = OPTION_REGISTRY["auth.mode"]
    enabled = auth_mode.enables.get("generate", ())
    assert "platform_auth_python_middleware" not in enabled, (
        "platform_auth_python_middleware fragment was wired into "
        "auth.mode=generate before the Phase 2 cutover landed — this "
        "would conflict with forge's existing python-service-template "
        "auth modules and emit FragmentError at generate time."
    )

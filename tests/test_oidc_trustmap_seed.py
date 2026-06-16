"""Behavioural gate for the ``oidc_generic`` trust-map *seed* (fail-closed).

Background. ``oidc_generic`` builds its :class:`AuthGuard` (``oidc_auth.py``
``build_oidc_auth_guard``) over an :class:`InMemoryIssuerTrustMap`. The prior
fix (see ``test_oidc_trustmap.py``) made the SDK guard's *missing-record* path
permissive by default so an EMPTY map would not reject every token. That kept
the provider working but left it unable to fail-closed: an attacker presenting
a token minted by some *other* issuer (for an unknown tenant) sailed through.

Better posture: SEED the trust map with the configured OIDC issuer bound to a
known/default tenant, and pass ``strict_trust=True`` to the guard. Then:

* a token for the configured issuer + seeded tenant is ACCEPTED;
* a token for the seeded tenant but a *different* issuer is REJECTED
  (per-tenant issuer binding); and
* a token for an *unknown* tenant is REJECTED (strict_trust fail-closed) —
  rather than silently accepted as before.

This must NOT re-break the empty-map case the SDK default protects (the SDK
guard's permissive missing-record default stays unchanged for other callers);
it only changes what the *oidc installer* wires.

These tests load the real ``oidc_auth.build_oidc_auth_guard`` by path — with
the generated project's heavy runtime deps (FastAPI, ``app.*``, ``forge_core``,
the middleware shim) stubbed and the real SDK ``AuthGuard`` / ``trust`` modules
loaded — then drive the guard's trust-enforcement path directly.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from uuid import UUID

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SDK_SRC = (
    _ROOT
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_sdk"
    / "python"
    / "files"
    / "packages"
    / "platform-auth"
    / "src"
    / "platform_auth"
)
_OIDC_FILES = (
    _ROOT
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_oidc"
    / "python"
    / "files"
    / "src"
    / "app"
    / "security"
)


def _load_by_path(module_name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _install_platform_auth() -> tuple[types.ModuleType, types.ModuleType]:
    """Build a ``platform_auth`` package exposing the real ``AuthGuard`` +
    ``trust`` symbols (and lightweight stubs for the crypto/JWKS collaborators
    the trust path never touches), so ``oidc_auth`` can ``from platform_auth
    import (...)`` exactly as it does in the generated project."""
    pkg = types.ModuleType("platform_auth")
    pkg.__path__ = [str(_SDK_SRC)]  # type: ignore[attr-defined]
    sys.modules["platform_auth"] = pkg

    exceptions = _load_by_path("platform_auth.exceptions", _SDK_SRC / "exceptions.py")

    if "cachetools" not in sys.modules:
        cachetools_stub = types.ModuleType("cachetools")

        class _TTLCache(dict):  # pragma: no cover - unused by these tests
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__()

        cachetools_stub.TTLCache = _TTLCache  # type: ignore[attr-defined]
        sys.modules["cachetools"] = cachetools_stub
    trust = _load_by_path("platform_auth.trust", _SDK_SRC / "trust.py")

    # ``auth_guard`` imports these at module scope but the trust-enforcement
    # path never reaches the crypto / JWKS / may-act machinery.
    jwt_stub = types.ModuleType("jwt")
    jwt_exc = types.ModuleType("jwt.exceptions")
    for name in (
        "DecodeError",
        "ExpiredSignatureError",
        "ImmatureSignatureError",
        "InvalidAudienceError",
        "InvalidIssuerError",
        "InvalidSignatureError",
        "InvalidTokenError",
        "MissingRequiredClaimError",
    ):
        setattr(jwt_exc, name, type(name, (Exception,), {}))
    jwt_stub.exceptions = jwt_exc  # type: ignore[attr-defined]
    sys.modules["jwt"] = jwt_stub
    sys.modules["jwt.exceptions"] = jwt_exc

    # A JWKSCache stub the installer can construct + ``register_issuer`` on.
    jwks_mod = types.ModuleType("platform_auth.jwks")

    class _JWKSCache:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.registered: dict[str, str] = {}

        def register_issuer(self, issuer: str, uri: str) -> None:
            self.registered[issuer] = uri

    jwks_mod.JWKSCache = _JWKSCache  # type: ignore[attr-defined]
    sys.modules["platform_auth.jwks"] = jwks_mod

    for sub, attrs in {
        "platform_auth.identity": ("IdentityContext",),
        "platform_auth.may_act": ("MayActPolicy",),
        "platform_auth.revocation": ("RevocationStore",),
    }.items():
        mod = types.ModuleType(sub)
        for attr in attrs:
            setattr(mod, attr, type(attr.split(".")[-1], (), {}))
        sys.modules[sub] = mod

    auth_guard = _load_by_path("platform_auth.auth_guard", _SDK_SRC / "auth_guard.py")

    # Surface the symbols ``oidc_auth`` imports from the package root.
    pkg.AuthGuard = auth_guard.AuthGuard  # type: ignore[attr-defined]
    pkg.InMemoryIssuerTrustMap = trust.InMemoryIssuerTrustMap  # type: ignore[attr-defined]
    pkg.TenantTrust = trust.TenantTrust  # type: ignore[attr-defined]
    pkg.JWKSCache = _JWKSCache  # type: ignore[attr-defined]

    class _StaticMayActPolicy:  # minimal stand-in; trust path never calls it
        def __init__(self, *args: object, **kwargs: object) -> None: ...

    pkg.StaticMayActPolicy = _StaticMayActPolicy  # type: ignore[attr-defined]
    pkg.exceptions = exceptions  # type: ignore[attr-defined]
    return auth_guard, trust


def _stub_generated_runtime() -> None:
    """Stub the generated-project modules ``oidc_auth`` imports at module scope
    (FastAPI, ``app.*``, ``forge_core``, the middleware shim) — none are touched
    by ``build_oidc_auth_guard`` once we pass the injection seams."""
    fastapi_stub = types.ModuleType("fastapi")
    fastapi_stub.FastAPI = type("FastAPI", (), {})  # type: ignore[attr-defined]
    sys.modules["fastapi"] = fastapi_stub

    # ``app`` package + the submodules imported by ``oidc_auth``.
    app_pkg = types.ModuleType("app")
    app_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["app"] = app_pkg

    app_core = types.ModuleType("app.core")
    app_core.__path__ = []  # type: ignore[attr-defined]
    sys.modules["app.core"] = app_core

    lifecycle = types.ModuleType("app.core.lifecycle")
    lifecycle.build_auth_guard = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["app.core.lifecycle"] = lifecycle

    config_mod = types.ModuleType("app.core.config")
    config_mod.Settings = type("Settings", (), {})  # type: ignore[attr-defined]
    sys.modules["app.core.config"] = config_mod

    app_security = types.ModuleType("app.security")
    app_security.__path__ = [str(_OIDC_FILES)]  # type: ignore[attr-defined]
    sys.modules["app.security"] = app_security

    # Load the real, dependency-light oidc_config so ``OIDCSettings`` is real.
    _load_by_path("app.security.oidc_config", _OIDC_FILES / "oidc_config.py")

    # Discovery imports httpx (available) but the installer never resolves when
    # we pass ``jwks_uri=``; stub it to avoid pulling its whole import chain.
    discovery = types.ModuleType("app.security.oidc_discovery")
    discovery.OIDCDiscovery = type("OIDCDiscovery", (), {})  # type: ignore[attr-defined]
    sys.modules["app.security.oidc_discovery"] = discovery

    forge_core = types.ModuleType("forge_core")
    forge_core.__path__ = []  # type: ignore[attr-defined]
    sys.modules["forge_core"] = forge_core
    fc_domain = types.ModuleType("forge_core.domain")
    fc_domain.__path__ = []  # type: ignore[attr-defined]
    sys.modules["forge_core.domain"] = fc_domain
    fc_config = types.ModuleType("forge_core.domain.config")
    fc_config.AuthConfig = type("AuthConfig", (), {})  # type: ignore[attr-defined]
    sys.modules["forge_core.domain.config"] = fc_config

    service_pkg = types.ModuleType("service")
    service_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["service"] = service_pkg
    svc_security = types.ModuleType("service.security")
    svc_security.__path__ = []  # type: ignore[attr-defined]
    sys.modules["service.security"] = svc_security
    setup_mod = types.ModuleType("service.security.platform_auth_setup")

    class _AuthGuardBundle:
        def __init__(self, *, guard, jwks, trust_map, may_act) -> None:
            self.guard = guard
            self.jwks = jwks
            self.trust_map = trust_map
            self.may_act = may_act

    setup_mod.AuthGuardBundle = _AuthGuardBundle  # type: ignore[attr-defined]
    sys.modules["service.security.platform_auth_setup"] = setup_mod


_AUTH_GUARD, _TRUST = _install_platform_auth()
_stub_generated_runtime()
_OIDC_AUTH = _load_by_path("app.security.oidc_auth", _OIDC_FILES / "oidc_auth.py")
_OIDC_CONFIG = sys.modules["app.security.oidc_config"]
_EXC = sys.modules["platform_auth.exceptions"]

_ISSUER = "https://issuer.example.com"


class _StubAuthConfig:
    """Minimal stand-in for ``forge_core.domain.config.AuthConfig``."""

    def __init__(self, tenant_id_claim: str = "https://forge/tenant_id") -> None:
        self.tenant_id_claim = tenant_id_claim


def _build_guard():
    """Build the oidc guard via the real installer path, with the injection
    seams set so no network / crypto is touched. Returns the AuthGuardBundle."""
    settings = _OIDC_CONFIG.OIDCSettings(issuer=_ISSUER + "/", audience="svc-knowledge")
    return _OIDC_AUTH.build_oidc_auth_guard(
        _StubAuthConfig(),
        settings,
        jwks_uri="https://issuer.example.com/keys",
    )


def _seeded_tenant():
    """The tenant the seeded trust map registers (read from the seeded map)."""
    bundle = _build_guard()
    records = bundle.trust_map._records  # type: ignore[attr-defined]
    assert records, "expected the oidc installer to SEED the trust map"
    return next(iter(records))


def test_configured_issuer_is_seeded_and_accepted() -> None:
    """After install, the trust map is POPULATED with the configured issuer for
    a known tenant, so a token presenting that issuer + tenant is ACCEPTED."""
    bundle = _build_guard()
    records = bundle.trust_map._records  # type: ignore[attr-defined]
    assert records, (
        "oidc installer must SEED the trust map with the configured issuer — "
        "an empty map cannot fail-closed on unknown issuers"
    )
    tenant = next(iter(records))
    record = records[tenant]
    assert record.expected_issuer == _ISSUER, (
        "seeded record must bind the configured (normalised) issuer"
    )
    # Right issuer for the seeded tenant → accepted (no raise).
    asyncio.run(bundle.guard._enforce_trust(tenant, _ISSUER))


def test_strict_trust_is_enabled_so_unknown_tenant_is_rejected() -> None:
    """The guard must be built with strict_trust=True so an UNKNOWN tenant
    (not in the seeded map) fails closed instead of being permissively
    accepted by the SDK's missing-record default."""
    bundle = _build_guard()
    assert bundle.guard._strict_trust is True, (
        "oidc installer must pass strict_trust=True so unknown issuers/tenants "
        "fail closed"
    )
    unknown = UUID("99999999-9999-9999-9999-999999999999")
    with pytest.raises((_EXC.IssuerNotTrusted, _EXC.InvalidToken)):
        asyncio.run(bundle.guard._enforce_trust(unknown, _ISSUER))


def test_seeded_tenant_rejects_wrong_issuer() -> None:
    """Per-tenant issuer binding still holds: the seeded tenant presenting a
    *different* issuer is rejected (an attacker's foreign-issuer token is not
    accepted just because it claims the seeded tenant)."""
    bundle = _build_guard()
    tenant = _seeded_tenant()
    with pytest.raises(_EXC.IssuerNotTrusted):
        asyncio.run(bundle.guard._enforce_trust(tenant, "https://evil.example.com"))

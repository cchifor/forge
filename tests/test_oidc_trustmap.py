"""Behavioural regression for the ``oidc_generic`` empty-trust-map footgun.

The ``oidc_generic`` provider builds its :class:`AuthGuard` over an *empty*
``InMemoryIssuerTrustMap`` (``oidc_auth.py`` ``build_oidc_auth_guard``). The
platform-auth SDK ``AuthGuard._enforce_trust`` is reached whenever
``trust_map is not None`` — and with an empty map every token resolves to a
``None`` trust record. If that ``None`` path is *fail-closed* (raise
``InvalidToken("unknown tenant ...")``), the provider authenticates *nobody*:
every structurally-valid token from the configured issuer is rejected 401.

The sibling ``forge_core.security.guard.AuthGuard`` already solved this: its
``_enforce_trust`` is permissive on a missing record unless ``strict_trust``
is set (default ``False``). The platform-auth SDK guard must match that
parity so the ``oidc_generic`` empty-map install path accepts valid tokens.

These tests load the real SDK ``AuthGuard`` + ``InMemoryIssuerTrustMap`` by
path (stubbing the heavy ``jwt`` / FastAPI / crypto deps that are absent in
forge's own env) and exercise the empty-map runtime path directly — the exact
path no shipped test covers (the SDK's own fixtures all *populate* the map).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from uuid import UUID

import pytest

_SDK_SRC = (
    Path(__file__).resolve().parent.parent
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


def _load_by_path(module_name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_sdk_auth_guard() -> tuple[types.ModuleType, types.ModuleType]:
    """Load the real platform-auth ``AuthGuard`` + ``trust`` modules.

    ``auth_guard.py`` imports ``jwt`` and several ``platform_auth`` submodules
    at module scope. ``jwt`` (PyJWT), ``cryptography`` and the rest are runtime
    deps of the *generated* project, not of forge — so we stub the ones we
    don't exercise and load the real ``exceptions`` + ``trust`` modules we do.
    """
    # Parent package shell so ``from platform_auth.X import ...`` resolves.
    pkg = types.ModuleType("platform_auth")
    pkg.__path__ = [str(_SDK_SRC)]  # type: ignore[attr-defined]
    sys.modules["platform_auth"] = pkg

    # Real, stdlib-only exception hierarchy (the slugs are part of the contract).
    exceptions = _load_by_path("platform_auth.exceptions", _SDK_SRC / "exceptions.py")

    # ``trust.py`` only needs ``cachetools.TTLCache`` for the *caching* wrapper,
    # which these tests don't touch. A trivial stub lets the real module — and
    # the real ``InMemoryIssuerTrustMap`` / ``TenantTrust`` — load unchanged.
    if "cachetools" not in sys.modules:
        cachetools_stub = types.ModuleType("cachetools")

        class _TTLCache(dict):  # pragma: no cover - unused by these tests
            def __init__(self, *args: object, **kwargs: object) -> None:
                super().__init__()

        cachetools_stub.TTLCache = _TTLCache  # type: ignore[attr-defined]
        sys.modules["cachetools"] = cachetools_stub
    trust = _load_by_path("platform_auth.trust", _SDK_SRC / "trust.py")

    # Stub the submodules ``auth_guard`` imports at module scope but that these
    # tests never reach (we call ``_enforce_trust`` directly, no crypto/JWKS).
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

    for sub, attrs in {
        "platform_auth.identity": ("IdentityContext",),
        "platform_auth.jwks": ("JWKSCache",),
        "platform_auth.may_act": ("MayActPolicy",),
        "platform_auth.revocation": ("RevocationStore",),
    }.items():
        mod = types.ModuleType(sub)
        for attr in attrs:
            setattr(mod, attr, type(attr.split(".")[-1], (), {}))
        sys.modules[sub] = mod

    auth_guard = _load_by_path("platform_auth.auth_guard", _SDK_SRC / "auth_guard.py")
    return auth_guard, trust


_AUTH_GUARD, _TRUST = _load_sdk_auth_guard()
_EXC = sys.modules["platform_auth.exceptions"]

_TENANT = UUID("11111111-1111-1111-1111-111111111111")
_ISSUER = "https://issuer.example.com"


def _empty_map_guard():
    """Construct an AuthGuard exactly as ``oidc_generic`` does: empty trust map."""
    return _AUTH_GUARD.AuthGuard(
        audience="svc-knowledge",
        jwks=object(),  # never touched by _enforce_trust
        trust_map=_TRUST.InMemoryIssuerTrustMap(),  # <-- empty, like oidc_auth.py:102
        algorithms=("RS256",),
    )


def test_empty_trust_map_accepts_unknown_tenant() -> None:
    """The oidc_generic install path: an empty trust map must NOT reject a
    valid token. ``_enforce_trust`` on an unregistered tenant must be
    permissive by default (parity with forge_core's ``strict_trust=False``)."""
    guard = _empty_map_guard()
    # Must not raise — the empty-map default is permissive single-issuer dev.
    asyncio.run(guard._enforce_trust(_TENANT, _ISSUER))


def test_strict_trust_still_fails_closed_when_requested() -> None:
    """Opt-in fail-closed must remain available: a deployment that *wants*
    every tenant registered passes ``strict_trust=True`` and still gets a
    rejection on an unknown tenant."""
    guard = _AUTH_GUARD.AuthGuard(
        audience="svc-knowledge",
        jwks=object(),
        trust_map=_TRUST.InMemoryIssuerTrustMap(),
        algorithms=("RS256",),
        strict_trust=True,
    )
    with pytest.raises((_EXC.IssuerNotTrusted, _EXC.InvalidToken)):
        asyncio.run(guard._enforce_trust(_TENANT, _ISSUER))


def test_populated_trust_map_still_enforces_issuer_binding() -> None:
    """The fix must not weaken the *populated* path: a registered tenant whose
    token presents the wrong issuer is still rejected (in_memory parity)."""
    trust = _TRUST.InMemoryIssuerTrustMap()
    trust.set(_TENANT, _TRUST.TenantTrust(expected_issuer=_ISSUER, suspended=False))
    guard = _AUTH_GUARD.AuthGuard(
        audience="svc-knowledge",
        jwks=object(),
        trust_map=trust,
        algorithms=("RS256",),
    )
    # Right issuer → accepted.
    asyncio.run(guard._enforce_trust(_TENANT, _ISSUER))
    # Wrong issuer → rejected.
    with pytest.raises(_EXC.IssuerNotTrusted):
        asyncio.run(guard._enforce_trust(_TENANT, "https://evil.example.com"))


def test_oidc_install_path_is_not_fail_closed_in_source() -> None:
    """Structural backstop: the oidc provider builds an EMPTY trust map, so the
    SDK guard it constructs must tolerate that empty map (either by a permissive
    default or an explicit flag). Guard against a future edit that silently
    flips the empty-map default back to fail-closed."""
    oidc_src = (
        Path(__file__).resolve().parent.parent
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
        / "oidc_auth.py"
    ).read_text(encoding="utf-8")
    # The provider still constructs an empty InMemoryIssuerTrustMap by default.
    assert "InMemoryIssuerTrustMap()" in oidc_src
    # And the SDK guard's empty-map path is permissive by default: the
    # strict_trust knob exists and defaults to False (not True).
    guard_src = (_SDK_SRC / "auth_guard.py").read_text(encoding="utf-8")
    assert "strict_trust" in guard_src, (
        "SDK AuthGuard must expose the strict_trust escape so the oidc empty-map "
        "path can be permissive (parity with forge_core.security.guard.AuthGuard)"
    )
    assert "strict_trust: bool = False" in guard_src, (
        "strict_trust must default to False (permissive) so the oidc_generic "
        "empty-map install path accepts valid tokens out of the box"
    )

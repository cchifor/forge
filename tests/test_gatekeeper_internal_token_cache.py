"""A1: the gatekeeper internal-token cache must key by *credential*, not owner.

The machine (API-key) auth track mints an internal ES256 JWT and caches it
under a synthetic Keycloak ``jti``. That jti was derived only from the
caller's ``owner`` sub (``api-key:<owner>``), so two API keys created by the
same admin — or two keys that share an ``owner`` value across tenants —
collapsed onto ONE cache entry. Whichever request minted first won, and every
later request under that owner was served the *first* key's bearer (its roles
and tenant), a privilege escalation / cross-tenant identity-confusion bug.
Downstream services trust the bearer's claims, so the served token is
authoritative.

Two guards, both exercised here:
1. the cache identity for an API key is per-key (tenant_id + key_id), never
   just the owner;
2. defense-in-depth — a verified cache hit whose decoded identity does not
   match the request is treated as a miss and re-minted.

Loads the shipped gatekeeper template modules in isolation (mirroring
tests/test_gatekeeper_apikeys.py) with heavy deps stubbed.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

_GK = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_gatekeeper"
    / "all"
    / "files"
    / "deploy"
    / "infra"
    / "gatekeeper"
    / "src"
    / "app"
    / "gatekeeper"
)

TENANT_CLAIM = "https://forge/tenant_id"


def _load_module(name: str, path: Path) -> types.ModuleType:
    for pkg in ("app", "app.gatekeeper"):
        sys.modules.setdefault(pkg, types.ModuleType(pkg))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_apikeys() -> types.ModuleType:
    redis_mod = types.ModuleType("app.gatekeeper.redis")
    redis_mod.get_redis = lambda: None  # type: ignore[attr-defined]
    sys.modules["app.gatekeeper.redis"] = redis_mod
    return _load_module("gk_apikeys_a1", _GK / "apikeys.py")


def _load_cache() -> types.ModuleType:
    helpers = types.ModuleType("app.gatekeeper.helpers")
    helpers.JWTPayload = dict  # type: ignore[attr-defined]
    sys.modules["app.gatekeeper.helpers"] = helpers

    internal_token = types.ModuleType("app.gatekeeper.internal_token")
    internal_token.AuthMethod = str  # type: ignore[attr-defined]
    internal_token.mint_internal_token = lambda *a, **k: ("UNUSED", 0)  # type: ignore[attr-defined]
    sys.modules["app.gatekeeper.internal_token"] = internal_token

    key_store = types.ModuleType("app.gatekeeper.key_store")
    key_store.KeyRing = type("KeyRing", (), {})  # type: ignore[attr-defined]
    sys.modules["app.gatekeeper.key_store"] = key_store

    # internal_token_cache does `import jwt as pyjwt`; PyJWT is absent in forge
    # CI and is only touched inside _verify_cached_token (monkeypatched here).
    sys.modules.setdefault("jwt", types.ModuleType("jwt"))

    return _load_module("gk_internal_cache_a1", _GK / "internal_token_cache.py")


class _FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}

    async def get(self, key: str):
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex=None) -> None:
        self.kv[key] = value

    async def delete(self, key: str) -> None:
        self.kv.pop(key, None)


class TestApiKeyCacheSubjectIsPerKey:
    def test_two_keys_same_owner_get_distinct_cache_subject(self) -> None:
        mod = _load_apikeys()
        rec1 = mod.APIKeyRecord(
            key_id="k1", tenant_id="tenant-A", name="n1", roles=["viewer"], owner="admin-A"
        )
        rec2 = mod.APIKeyRecord(
            key_id="k2", tenant_id="tenant-A", name="n2", roles=["admin"], owner="admin-A"
        )
        assert mod.cache_subject(rec1) != mod.cache_subject(rec2), (
            "two API keys created by the same admin must not share an "
            "internal-token cache identity"
        )

    def test_cache_subject_distinguishes_tenants(self) -> None:
        mod = _load_apikeys()
        rec_a = mod.APIKeyRecord(
            key_id="k1", tenant_id="tenant-A", name="n", roles=["r"], owner="unknown"
        )
        rec_b = mod.APIKeyRecord(
            key_id="k1", tenant_id="tenant-B", name="n", roles=["r"], owner="unknown"
        )
        assert mod.cache_subject(rec_a) != mod.cache_subject(rec_b), (
            "keys with a shared owner value across tenants must not collide"
        )


class TestCacheIdentityCheck:
    def _make_cache(self, mod: types.ModuleType, fake: _FakeRedis):
        return mod.InternalTokenCache(
            redis=fake,
            key_ring=object(),
            issuer="iss",
            audience="aud",
            ttl_seconds=300,
        )

    def test_identity_mismatch_on_hit_remints(self) -> None:
        mod = _load_cache()
        fake = _FakeRedis()
        cache = self._make_cache(mod, fake)
        payload = {"sub": "owner-B", TENANT_CLAIM: "tenant-A", "jti": "api-key:tenant-A:k2"}
        fake.kv[cache._cache_key(payload["jti"])] = "CACHED_TOKEN_FOR_A"
        # The cached token decodes to a DIFFERENT identity than the request.
        cache._verify_cached_token = lambda token: {
            "sub": "owner-A",
            TENANT_CLAIM: "tenant-A",
            "exp": 9999999999,
        }
        cache._mint_fresh = lambda kp, am: ("FRESH_TOKEN", 9999999999)
        token, _ = asyncio.run(
            cache.get_or_mint(keycloak_payload=payload, auth_method="api_key")
        )
        assert token == "FRESH_TOKEN", (
            "a cache hit whose identity does not match the request must be "
            "re-minted, not served verbatim"
        )

    def test_identity_match_on_hit_serves_cache(self) -> None:
        mod = _load_cache()
        fake = _FakeRedis()
        cache = self._make_cache(mod, fake)
        payload = {"sub": "owner-A", TENANT_CLAIM: "tenant-A", "jti": "api-key:tenant-A:k1"}
        fake.kv[cache._cache_key(payload["jti"])] = "CACHED_TOKEN_FOR_A"
        cache._verify_cached_token = lambda token: {
            "sub": "owner-A",
            TENANT_CLAIM: "tenant-A",
            "exp": 9999999999,
        }
        cache._mint_fresh = lambda kp, am: ("FRESH_TOKEN", 9999999999)
        token, _ = asyncio.run(
            cache.get_or_mint(keycloak_payload=payload, auth_method="api_key")
        )
        assert token == "CACHED_TOKEN_FOR_A", "matching identity must serve the cache"

"""Behavioural tests for the Gatekeeper's API-key Redis operations.

Loaded from the template path (with a stubbed ``app.gatekeeper.redis``) so the
tests validate what forge ships to generated projects without needing a real
redis client installed in forge CI — mirroring ``tests/test_mcp_audit.py``.

Security focus: ``revoke_api_key`` must be tenant-scoped. An admin of one
tenant must NOT be able to revoke another tenant's key by knowing its hash
(cross-tenant IDOR), even though both reach the same lower-level helper.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

_APIKEYS_PATH = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "auth"
    / "templates"
    / "platform_auth_gatekeeper"
    / "all"
    / "files"
    / "infra"
    / "gatekeeper"
    / "src"
    / "app"
    / "gatekeeper"
    / "apikeys.py"
)


class _FakeRedis:
    """Minimal in-memory async stand-in for the Redis subset apikeys.py uses."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.kv.get(key)

    async def set(self, key: str, value: str) -> None:
        self.kv[key] = value

    async def delete(self, key: str) -> int:
        existed = key in self.kv
        self.kv.pop(key, None)
        return 1 if existed else 0

    async def sadd(self, key: str, member: str) -> None:
        self.sets.setdefault(key, set()).add(member)

    async def srem(self, key: str, member: str) -> None:
        self.sets.get(key, set()).discard(member)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))


def _load_apikeys_module() -> tuple[types.ModuleType, _FakeRedis]:
    """Import the template ``apikeys.py`` with ``app.gatekeeper.redis`` stubbed.

    ``apikeys.py`` only depends on ``from app.gatekeeper.redis import get_redis``
    plus stdlib, so a tiny fake module is enough — no real ``redis`` package
    (absent in forge CI) is needed.
    """
    fake = _FakeRedis()
    redis_mod = types.ModuleType("app.gatekeeper.redis")
    redis_mod.get_redis = lambda: fake  # type: ignore[attr-defined]
    for name in ("app", "app.gatekeeper"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["app.gatekeeper.redis"] = redis_mod

    spec = importlib.util.spec_from_file_location("gk_apikeys_under_test", _APIKEYS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gk_apikeys_under_test"] = module
    spec.loader.exec_module(module)
    return module, fake


async def _seed_key(module, fake, *, key_hash: str, tenant_id: str) -> None:
    await module.store_api_key(
        key_hash,
        key_id="kid",
        tenant_id=tenant_id,
        name="label",
        roles=["admin"],
        owner="owner",
    )


class TestRevokeTenantScoping:
    def test_revoke_rejects_cross_tenant(self) -> None:
        """An admin of tenant-A must not revoke tenant-B's key by its hash."""
        module, fake = _load_apikeys_module()
        asyncio.run(_seed_key(module, fake, key_hash="hashB", tenant_id="tenant-B"))

        revoked = asyncio.run(module.revoke_api_key("hashB", "tenant-A"))

        assert revoked is False, "cross-tenant revoke must report failure"
        assert (
            asyncio.run(fake.get("apikey:hashB")) is not None
        ), "tenant-B's key must survive a cross-tenant revoke attempt"

    def test_revoke_allows_same_tenant(self) -> None:
        module, fake = _load_apikeys_module()
        asyncio.run(_seed_key(module, fake, key_hash="hashB", tenant_id="tenant-B"))

        revoked = asyncio.run(module.revoke_api_key("hashB", "tenant-B"))

        assert revoked is True
        assert asyncio.run(fake.get("apikey:hashB")) is None

    def test_revoke_unknown_key_returns_false(self) -> None:
        module, fake = _load_apikeys_module()
        assert asyncio.run(module.revoke_api_key("nope", "tenant-A")) is False

    def test_revoke_does_not_touch_other_tenant_index(self) -> None:
        """A cross-tenant attempt must not remove the key from B's index."""
        module, fake = _load_apikeys_module()
        asyncio.run(_seed_key(module, fake, key_hash="hashB", tenant_id="tenant-B"))

        asyncio.run(module.revoke_api_key("hashB", "tenant-A"))

        assert "hashB" in asyncio.run(fake.smembers("apikeys_by_tenant:tenant-B"))

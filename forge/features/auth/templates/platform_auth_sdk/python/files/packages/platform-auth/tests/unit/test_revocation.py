"""RevocationStore tests using fakeredis as an in-memory drop-in."""

from __future__ import annotations

import pytest
from fakeredis import aioredis as fakeaioredis
from redis.exceptions import ConnectionError as RedisConnectionError

from platform_auth.revocation import RevocationStore


@pytest.fixture
async def redis_client():
    """Async fakeredis client suitable as a drop-in for redis.asyncio.Redis."""
    client = fakeaioredis.FakeRedis(decode_responses=False)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def store(redis_client):
    return RevocationStore(redis_client)


class TestAdd:
    async def test_add_then_is_revoked(self, store: RevocationStore):
        await store.add("jti-1", ttl_seconds=60)
        assert await store.is_revoked("jti-1") is True

    async def test_unknown_jti_is_not_revoked(self, store: RevocationStore):
        assert await store.is_revoked("never-added") is False

    async def test_empty_jti_raises(self, store: RevocationStore):
        with pytest.raises(ValueError, match="non-empty"):
            await store.add("", ttl_seconds=60)

    async def test_zero_or_negative_ttl_is_noop(self, store: RevocationStore):
        await store.add("jti-already-expired", ttl_seconds=0)
        assert await store.is_revoked("jti-already-expired") is False

        await store.add("jti-also-already-expired", ttl_seconds=-5)
        assert await store.is_revoked("jti-also-already-expired") is False

    async def test_add_is_idempotent(self, store: RevocationStore):
        await store.add("jti-2", ttl_seconds=60)
        await store.add("jti-2", ttl_seconds=120)
        assert await store.is_revoked("jti-2") is True


class TestIsRevoked:
    async def test_empty_jti_returns_false(self, store: RevocationStore):
        # AuthGuard rejects jti-less tokens before reaching us; assert we don't crash.
        assert await store.is_revoked("") is False


class TestKeyPrefix:
    async def test_default_prefix(self, redis_client):
        store = RevocationStore(redis_client)
        await store.add("jti-3", ttl_seconds=60)
        # Verify the key is namespaced
        assert await redis_client.exists(b"revoked:jti:jti-3")

    async def test_custom_prefix(self, redis_client):
        store = RevocationStore(redis_client, key_prefix="custom:rev")
        await store.add("jti-4", ttl_seconds=60)
        assert await redis_client.exists(b"custom:rev:jti-4")
        # And not under the default prefix:
        assert not await redis_client.exists(b"revoked:jti:jti-4")

    async def test_empty_prefix_rejected(self, redis_client):
        with pytest.raises(ValueError, match="non-empty"):
            RevocationStore(redis_client, key_prefix="")


class TestFailureModes:
    async def test_redis_outage_during_check_fails_open(
        self,
        redis_client,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """If Redis is unreachable, is_revoked must NOT raise — that would
        flatline every service. Returns False (fail open) and logs a warning.
        See module docstring rationale."""
        store = RevocationStore(redis_client)

        async def _boom(*args, **kwargs):
            raise RedisConnectionError("simulated outage")

        monkeypatch.setattr(redis_client, "exists", _boom)

        with caplog.at_level("WARNING"):
            result = await store.is_revoked("jti-doesnt-matter")

        assert result is False
        assert any(
            "revocation_check_failed_fail_open" in record.message for record in caplog.records
        )

    async def test_redis_outage_during_add_raises(
        self,
        redis_client,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """In contrast, add() failures DO raise — the operator who called
        revoke() must know it didn't take."""
        store = RevocationStore(redis_client)

        async def _boom(*args, **kwargs):
            raise RedisConnectionError("simulated outage")

        monkeypatch.setattr(redis_client, "set", _boom)

        with pytest.raises(RedisConnectionError):
            await store.add("jti-add-fail", ttl_seconds=60)

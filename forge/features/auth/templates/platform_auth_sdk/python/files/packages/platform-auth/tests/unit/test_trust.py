"""IssuerTrustMap implementations."""

from __future__ import annotations

from uuid import UUID

import pytest

from platform_auth.trust import (
    CachingIssuerTrustMap,
    InMemoryIssuerTrustMap,
    IssuerTrustMap,
    TenantTrust,
)

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")
ISSUER_DEFAULT = "https://idp.example.com/realms/platform"
ISSUER_ENTERPRISE = "https://idp.example.com/realms/enterprise-x"


class TestInMemoryIssuerTrustMap:
    async def test_set_and_get(self):
        trust = InMemoryIssuerTrustMap()
        trust.set(TENANT_A, TenantTrust(expected_issuer=ISSUER_DEFAULT))
        record = await trust.get(TENANT_A)
        assert record is not None
        assert record.expected_issuer == ISSUER_DEFAULT
        assert record.suspended is False

    async def test_unknown_tenant_returns_none(self):
        trust = InMemoryIssuerTrustMap()
        assert await trust.get(TENANT_A) is None

    async def test_remove(self):
        trust = InMemoryIssuerTrustMap()
        trust.set(TENANT_A, TenantTrust(expected_issuer=ISSUER_DEFAULT))
        trust.remove(TENANT_A)
        assert await trust.get(TENANT_A) is None
        # Idempotent remove on unknown tenant.
        trust.remove(TENANT_A)

    async def test_suspend_then_unsuspend(self):
        trust = InMemoryIssuerTrustMap()
        trust.set(TENANT_A, TenantTrust(expected_issuer=ISSUER_DEFAULT))
        trust.suspend(TENANT_A)
        record = await trust.get(TENANT_A)
        assert record is not None and record.suspended is True
        trust.unsuspend(TENANT_A)
        record = await trust.get(TENANT_A)
        assert record is not None and record.suspended is False

    async def test_suspend_unknown_raises(self):
        trust = InMemoryIssuerTrustMap()
        with pytest.raises(KeyError):
            trust.suspend(TENANT_A)

    async def test_constructor_records(self):
        trust = InMemoryIssuerTrustMap(
            {
                TENANT_A: TenantTrust(expected_issuer=ISSUER_DEFAULT),
                TENANT_B: TenantTrust(expected_issuer=ISSUER_ENTERPRISE),
            }
        )
        record_a = await trust.get(TENANT_A)
        record_b = await trust.get(TENANT_B)
        assert record_a is not None and record_a.expected_issuer == ISSUER_DEFAULT
        assert record_b is not None and record_b.expected_issuer == ISSUER_ENTERPRISE

    def test_implements_protocol(self):
        trust = InMemoryIssuerTrustMap()
        assert isinstance(trust, IssuerTrustMap)


class TestTenantTrust:
    def test_is_frozen(self):
        record = TenantTrust(expected_issuer=ISSUER_DEFAULT)
        with pytest.raises(AttributeError):
            record.suspended = True  # type: ignore[misc]

    def test_default_not_suspended(self):
        record = TenantTrust(expected_issuer=ISSUER_DEFAULT)
        assert record.suspended is False


class TestCachingIssuerTrustMap:
    class _CountingBackend(IssuerTrustMap):
        def __init__(self, records: dict[UUID, TenantTrust]):
            self.records = records
            self.calls = 0

        async def get(self, tenant_id: UUID) -> TenantTrust | None:
            self.calls += 1
            return self.records.get(tenant_id)

    async def test_caches_positive_lookups(self):
        backend = self._CountingBackend({TENANT_A: TenantTrust(expected_issuer=ISSUER_DEFAULT)})
        cache = CachingIssuerTrustMap(backend, ttl_seconds=60)

        for _ in range(5):
            await cache.get(TENANT_A)
        assert backend.calls == 1

    async def test_caches_negative_lookups(self):
        """Important: negative results must be cached so a typo'd tenant
        doesn't pin the upstream under a thundering herd."""
        backend = self._CountingBackend({})
        cache = CachingIssuerTrustMap(backend, ttl_seconds=60)

        for _ in range(5):
            assert await cache.get(TENANT_A) is None
        assert backend.calls == 1

    async def test_independent_keys_share_no_state(self):
        backend = self._CountingBackend(
            {
                TENANT_A: TenantTrust(expected_issuer=ISSUER_DEFAULT),
                TENANT_B: TenantTrust(expected_issuer=ISSUER_ENTERPRISE),
            }
        )
        cache = CachingIssuerTrustMap(backend, ttl_seconds=60)
        await cache.get(TENANT_A)
        await cache.get(TENANT_B)
        # Two distinct lookups → two backend calls.
        assert backend.calls == 2

    async def test_invalidate(self):
        backend = self._CountingBackend({TENANT_A: TenantTrust(expected_issuer=ISSUER_DEFAULT)})
        cache = CachingIssuerTrustMap(backend, ttl_seconds=60)
        await cache.get(TENANT_A)
        cache.invalidate(TENANT_A)
        await cache.get(TENANT_A)
        assert backend.calls == 2

    async def test_clear(self):
        backend = self._CountingBackend(
            {
                TENANT_A: TenantTrust(expected_issuer=ISSUER_DEFAULT),
                TENANT_B: TenantTrust(expected_issuer=ISSUER_ENTERPRISE),
            }
        )
        cache = CachingIssuerTrustMap(backend, ttl_seconds=60)
        await cache.get(TENANT_A)
        await cache.get(TENANT_B)
        cache.clear()
        await cache.get(TENANT_A)
        await cache.get(TENANT_B)
        assert backend.calls == 4

    async def test_invalidate_unknown_is_noop(self):
        backend = self._CountingBackend({})
        cache = CachingIssuerTrustMap(backend, ttl_seconds=60)
        cache.invalidate(TENANT_A)  # no-op, no raise

    async def test_zero_ttl_rejected(self):
        backend = self._CountingBackend({})
        with pytest.raises(ValueError, match="ttl_seconds must be positive"):
            CachingIssuerTrustMap(backend, ttl_seconds=0)

    async def test_zero_max_entries_rejected(self):
        backend = self._CountingBackend({})
        with pytest.raises(ValueError, match="max_entries must be positive"):
            CachingIssuerTrustMap(backend, ttl_seconds=60, max_entries=0)

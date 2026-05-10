"""Tenant→issuer trust map and tenant suspension lookup.

In the hybrid-realm topology, a single Keycloak realm issues tokens for most
tenants, but enterprise-tier tenants opt into dedicated realms. Without an
explicit trust map a stolen token from realm B would be silently honored by
a service that did not know to expect it. The trust map is the answer:

* Each tenant has exactly one expected issuer.
* Tokens whose ``iss`` claim mismatches are rejected with
  :class:`platform_auth.IssuerNotTrusted`.
* The same lookup carries a tenant ``status`` so suspending a tenant is a
  cache-version bump rather than a token-revocation sweep.

The SDK ships:

* :class:`TenantTrust` — the data shape returned by a lookup.
* :class:`IssuerTrustMap` — the abstract Protocol every implementation
  satisfies.
* :class:`InMemoryIssuerTrustMap` — a simple dict-backed implementation,
  fine for tests and single-tenant dev deployments.
* :class:`CachingIssuerTrustMap` — wraps any implementation with a
  per-tenant TTL cache; the production wiring (a TMS gRPC client) goes
  inside this wrapper so every service caches identically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from cachetools import TTLCache


@dataclass(frozen=True, slots=True)
class TenantTrust:
    """Trust record for a single tenant.

    ``expected_issuer`` is the exact ``iss`` claim every token for this
    tenant must carry. ``suspended`` is a soft gate — a suspended tenant's
    tokens fail with :class:`platform_auth.TenantSuspended` (403) rather
    than 401, so clients can distinguish "your token is bad" from "your
    tenant is paused".
    """

    expected_issuer: str
    suspended: bool = False


@runtime_checkable
class IssuerTrustMap(Protocol):
    """Trust-map contract.

    Implementations are expected to be cheap to call from the request hot
    path; production wiring should put a TTL cache (60s by default) in
    front of the underlying source of truth (TMS gRPC).
    """

    async def get(self, tenant_id: UUID) -> TenantTrust | None:
        """Return the trust record for ``tenant_id``, or ``None`` if unknown.

        ``None`` means the tenant has no record at all; callers treat this
        as a hard failure (the token claimed a tenant that does not exist).
        """
        ...


class InMemoryIssuerTrustMap(IssuerTrustMap):
    """Dict-backed trust map.

    Useful for tests and for single-realm dev deployments where TMS isn't
    wired up yet. Mutating methods are sync; reads remain async to satisfy
    the protocol.
    """

    def __init__(self, records: dict[UUID, TenantTrust] | None = None) -> None:
        self._records: dict[UUID, TenantTrust] = dict(records) if records else {}

    def set(self, tenant_id: UUID, trust: TenantTrust) -> None:
        """Insert or replace the trust record for ``tenant_id``."""
        self._records[tenant_id] = trust

    def remove(self, tenant_id: UUID) -> None:
        """Remove the trust record for ``tenant_id``; no-op if absent."""
        self._records.pop(tenant_id, None)

    def suspend(self, tenant_id: UUID) -> None:
        """Mark ``tenant_id`` as suspended; raises ``KeyError`` if unknown."""
        record = self._records[tenant_id]
        self._records[tenant_id] = TenantTrust(
            expected_issuer=record.expected_issuer,
            suspended=True,
        )

    def unsuspend(self, tenant_id: UUID) -> None:
        """Mark ``tenant_id`` as active; raises ``KeyError`` if unknown."""
        record = self._records[tenant_id]
        self._records[tenant_id] = TenantTrust(
            expected_issuer=record.expected_issuer,
            suspended=False,
        )

    async def get(self, tenant_id: UUID) -> TenantTrust | None:
        return self._records.get(tenant_id)


class CachingIssuerTrustMap(IssuerTrustMap):
    """Wrap any :class:`IssuerTrustMap` with a TTL cache.

    Negative results (``None``) are cached for the same TTL so a typo'd
    tenant_id doesn't pin the upstream under a thundering herd. Suspension
    propagates to all consumers within ``ttl_seconds`` of TMS bumping the
    record — the plan explicitly calls this out as the suspension
    propagation mechanism.
    """

    _MISS = object()

    def __init__(
        self,
        backend: IssuerTrustMap,
        *,
        ttl_seconds: int = 60,
        max_entries: int = 10_000,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._backend = backend
        self._cache: TTLCache[UUID, object] = TTLCache(maxsize=max_entries, ttl=ttl_seconds)

    async def get(self, tenant_id: UUID) -> TenantTrust | None:
        cached = self._cache.get(tenant_id, self._MISS)
        if cached is not self._MISS:
            return cached  # type: ignore[return-value]
        value = await self._backend.get(tenant_id)
        # cachetools is sync and not asyncio-safe under concurrent writers;
        # last-write-wins is fine for this use case (idempotent values).
        self._cache[tenant_id] = value  # type: ignore[assignment]
        return value

    def invalidate(self, tenant_id: UUID) -> None:
        """Force-remove ``tenant_id`` from the cache.

        Use sparingly — the TTL is the documented propagation mechanism.
        Provided for ops "fix it now" scenarios.
        """
        self._cache.pop(tenant_id, None)

    def clear(self) -> None:
        """Drop all cached entries."""
        self._cache.clear()


__all__ = [
    "CachingIssuerTrustMap",
    "InMemoryIssuerTrustMap",
    "IssuerTrustMap",
    "TenantTrust",
]

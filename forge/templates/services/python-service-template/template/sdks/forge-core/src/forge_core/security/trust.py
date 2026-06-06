"""Tenant -> issuer trust map and tenant suspension lookup.

When more than one issuer can mint tokens, an explicit trust map ensures a
service only honours tokens from the issuer the tenant is bound to:

* Each tenant has exactly one expected issuer.
* Tokens whose ``iss`` claim mismatches are rejected with
  :class:`forge_core.security.IssuerNotTrusted`.
* The same lookup carries a ``suspended`` flag so suspending a tenant is a
  cache-version bump rather than a token-revocation sweep.

The generic layer ships the in-memory implementation (fine for tests and
single-issuer dev deployments). Production deployments with a multi-issuer
topology supply their own :class:`IssuerTrustMap` implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TenantTrust:
    """Trust record for a single tenant."""

    expected_issuer: str
    suspended: bool = False


@runtime_checkable
class IssuerTrustMap(Protocol):
    """Trust-map contract — cheap to call from the request hot path."""

    async def get(self, tenant_id: str) -> TenantTrust | None:
        """Return the trust record for ``tenant_id``, or ``None`` if unknown."""
        ...


class InMemoryIssuerTrustMap(IssuerTrustMap):
    """Dict-backed trust map.

    Useful for tests and single-issuer dev deployments. Mutating methods are
    sync; reads remain async to satisfy the protocol. An empty trust map is
    permissive: :class:`AuthGuard` only enforces trust for tenants that *have*
    a record, so the default in-memory map (no records) accepts any tenant —
    the single-issuer default. Populate it to enforce per-tenant issuers.
    """

    def __init__(self, records: dict[str, TenantTrust] | None = None) -> None:
        self._records: dict[str, TenantTrust] = dict(records) if records else {}

    def set(self, tenant_id: str, trust: TenantTrust) -> None:
        """Insert or replace the trust record for ``tenant_id``."""
        self._records[tenant_id] = trust

    def remove(self, tenant_id: str) -> None:
        """Remove the trust record for ``tenant_id``; no-op if absent."""
        self._records.pop(tenant_id, None)

    async def get(self, tenant_id: str) -> TenantTrust | None:
        return self._records.get(tenant_id)


__all__ = [
    "InMemoryIssuerTrustMap",
    "IssuerTrustMap",
    "TenantTrust",
]

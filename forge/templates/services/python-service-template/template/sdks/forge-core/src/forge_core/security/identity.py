"""IdentityContext — the verified identity of the caller.

Built by :class:`forge_core.security.AuthGuard` after a token survives
signature, issuer, audience, expiry, and trust checks. Frozen and hashable so
it can live in a ContextVar across async boundaries without surprise
mutation. ``raw_claims`` is provided for advanced uses (custom claim
extraction) but the typed accessors should be preferred.

The tenant id is kept as a plain ``str`` (not ``UUID``) so the generic layer
imposes no opinion on the tenant identifier's shape — a project that wants
UUID semantics validates the claim in its own claim mapper. This is the
Strive-decoupled generalisation of the platform's UUID-only identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from forge_core.security.scopes import scope_satisfies

_EMPTY_CLAIMS: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """A verified caller identity."""

    tenant_id: str
    subject: str
    roles: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)
    actor: str | None = None
    tenant_slug: str | None = None
    # raw_claims is informational only; excluded from eq/hash so two
    # identities with the same primary claims compare equal regardless of
    # incidental claim differences (and so the dataclass remains hashable).
    raw_claims: Mapping[str, Any] = field(default=_EMPTY_CLAIMS, compare=False)

    def has_scope(self, required: str) -> bool:
        """True if this identity's scopes satisfy ``required`` (wildcard-aware)."""
        return scope_satisfies(required, self.scopes)

    def has_any_scope(self, *required: str) -> bool:
        """True if any of ``required`` is satisfied by this identity's scopes."""
        return any(self.has_scope(s) for s in required)

    def has_all_scopes(self, *required: str) -> bool:
        """True if every scope in ``required`` is satisfied by this identity's scopes."""
        return all(self.has_scope(s) for s in required)

    @property
    def is_actor(self) -> bool:
        """True if this token was minted via on-behalf-of token-exchange."""
        return self.actor is not None


__all__ = ["IdentityContext"]

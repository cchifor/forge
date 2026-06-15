"""IdentityContext — verified identity of the caller.

Built by :class:`platform_auth.AuthGuard` after a token survives signature,
issuer, audience, expiry, revocation, and ``may_act`` checks. Repository
layers and policy decorators consume it; nothing else in the request should
touch raw JWT claims.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar
from uuid import UUID

from platform_auth.scopes import scope_satisfies

_EMPTY_CLAIMS: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """A verified caller identity.

    Frozen and hashable so it can live in a ContextVar across async boundaries
    without surprise mutation. ``raw_claims`` is provided for advanced uses
    (custom claim extraction) but typed accessors should be preferred.
    """

    PLATFORM_SUPPORT_READ: ClassVar[str] = "platform:support:read"
    PLATFORM_SUPPORT_WRITE: ClassVar[str] = "platform:support:write"

    tenant_id: UUID
    subject: str
    roles: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)
    actor: str | None = None
    # Optional human-readable tenant slug from the configured
    # ``tenant_slug_claim``. ``None`` when the JWT doesn't carry the
    # claim. Consumers that need a stable identifier should always
    # prefer ``tenant_id`` (UUID); the slug is for log labels and
    # human-facing error messages.
    tenant_slug: str | None = None
    # raw_claims is informational only; exclude from eq/hash so two
    # identities with the same primary claims compare equal regardless of
    # incidental claim differences (and so the dataclass remains hashable
    # — Mapping is not).
    raw_claims: Mapping[str, Any] = field(default=_EMPTY_CLAIMS, compare=False)

    def has_scope(self, required: str) -> bool:
        """True if this identity's scopes satisfy ``required``.

        Uses :func:`platform_auth.scope_satisfies` so wildcards
        (``<service>:*``, ``*``) are honored.
        """
        return scope_satisfies(required, self.scopes)

    def has_any_scope(self, *required: str) -> bool:
        """True if any of ``required`` is satisfied by this identity's scopes."""
        return any(self.has_scope(s) for s in required)

    def has_all_scopes(self, *required: str) -> bool:
        """True if every scope in ``required`` is satisfied by this identity's scopes."""
        return all(self.has_scope(s) for s in required)

    @property
    def is_platform_admin(self) -> bool:
        """True if the identity holds any cross-tenant ``platform:support`` scope.

        Cross-tenant access goes through this gate; ``AuthGuard`` and RLS GUC
        wiring use it to decide whether to skip the per-tenant filter, and
        every such access lands in the elevated audit feed.
        """
        return self.has_any_scope(
            self.PLATFORM_SUPPORT_READ,
            self.PLATFORM_SUPPORT_WRITE,
        )

    @property
    def is_actor(self) -> bool:
        """True if this token was minted via on-behalf-of token-exchange."""
        return self.actor is not None

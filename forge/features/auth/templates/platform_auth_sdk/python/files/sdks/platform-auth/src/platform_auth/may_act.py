"""may_act impersonation policy.

When service A obtains a token to act on behalf of a user when calling
service B, RFC 8693 records A in the resulting token's ``act`` claim. Without
a policy gate, *any* service with valid client_credentials can mint such a
token for any user — a compromised low-privilege service could elevate.

The :class:`MayActPolicy` says: for the destination audience ``B``, which
actor identities are authorized to appear in the ``act`` chain? AuthGuard
walks the chain and rejects with :class:`platform_auth.ActorNotAuthorized`
if any actor is not authorized for the current audience.

The policy is consulted by the verifier on every request. Implementations
should be O(1); the static implementation here is hashed-set membership.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class MayActPolicy(Protocol):
    """may_act contract."""

    def is_authorized(self, actor: str, audience: str) -> bool:
        """Return ``True`` if ``actor`` is allowed to act for ``audience``.

        ``actor`` is the identity recorded in a single ``act`` claim entry
        (typically a Keycloak client_id like ``svc-deepagent``). ``audience``
        is the destination service's expected ``aud`` value.

        The check is per-hop: for a chain ``[A, B]`` calling audience ``C``,
        the verifier asks ``is_authorized(A, C)`` and ``is_authorized(B, C)``
        and rejects if either is false.
        """
        ...


class StaticMayActPolicy(MayActPolicy):
    """Audience → set-of-allowed-actors policy.

    Loaded from config at startup; reload via :meth:`replace`. The empty
    policy denies everything — useful as a safe default before the config is
    wired up, since AuthGuard rejects on a False answer.
    """

    def __init__(self, allowlist: Mapping[str, Iterable[str]] | None = None) -> None:
        self._allowlist: dict[str, frozenset[str]] = {
            audience: frozenset(actors) for audience, actors in (allowlist or {}).items()
        }

    def is_authorized(self, actor: str, audience: str) -> bool:
        if not actor or not audience:
            return False
        allowed = self._allowlist.get(audience)
        if allowed is None:
            return False
        return actor in allowed

    def replace(self, allowlist: Mapping[str, Iterable[str]]) -> None:
        """Replace the policy in place; safe under concurrent reads."""
        new_lists = {audience: frozenset(actors) for audience, actors in allowlist.items()}
        self._allowlist = new_lists

    def authorized_actors_for(self, audience: str) -> frozenset[str]:
        """Return the authorized-actor set for ``audience`` (empty if none)."""
        return self._allowlist.get(audience, frozenset())


class AllowAllMayActPolicy(MayActPolicy):
    """Permit any actor to act for any audience.

    Reserved for testing and break-glass scenarios. Production deployments
    should never use this — the entire point of :class:`MayActPolicy` is to
    constrain impersonation. Instantiating this in production code is a lint
    error (the SDK exposes it from a separate module path so the audit trail
    is unambiguous).
    """

    def is_authorized(self, actor: str, audience: str) -> bool:
        return bool(actor) and bool(audience)


__all__ = [
    "AllowAllMayActPolicy",
    "MayActPolicy",
    "StaticMayActPolicy",
]

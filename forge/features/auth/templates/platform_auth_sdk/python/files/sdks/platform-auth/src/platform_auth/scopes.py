"""Platform scope namespace and hierarchy resolution.

Scopes follow a colon-delimited convention: ``<service>:<verb>`` for the per-
service scopes that gate ordinary endpoints, and ``platform:support:<verb>``
for cross-tenant operator access.

Hierarchy rules consulted by :func:`scope_satisfies`:

1. Exact match — held set contains the required scope literally.
2. Super-wildcard — held set contains ``*`` (covers everything; reserved for
   break-glass / debug clients).
3. Verb wildcard — held set contains ``<prefix>:*`` where ``<prefix>`` is
   every segment of the required scope except the last. So ``workflow:*``
   covers ``workflow:read`` but NOT ``workflow:admin:retry``; ``platform:support:*``
   covers ``platform:support:read`` but NOT ``platform:foo``.
4. Namespace wildcard — held set contains ``*:<tail>`` where ``<tail>`` is
   every segment except the first. ``*:read`` covers ``workflow:read`` and
   ``platform:support:read`` is covered by ``*:support:read``.

Deeper wildcard combinations (e.g. ``platform:*`` covering
``platform:support:read``) are intentionally not supported in v1; their
authorization semantics are too easy to misread. Add explicit wildcards to
the token instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

# The catalogue of services whose endpoints carry per-service scopes.
# Kept in one place so adding a new service is a one-line change.
_SERVICES: tuple[str, ...] = (
    "workflow",
    "knowledge",
    "mcp",
    "airlock",
    "integration",
    "deepagent",
    "notification",
    "profile",
    "sentinel",
    "tms",
)

_VERBS: tuple[str, ...] = ("read", "write", "admin")


class Scope(StrEnum):
    """Canonical platform scopes.

    Endpoints declare required scopes via :func:`platform_auth.require_scope`;
    Keycloak client-scope mappers translate roles → scopes at token issue
    time. New scopes land here first; ad-hoc string scopes in code are a lint
    error.
    """

    WORKFLOW_READ = "workflow:read"
    WORKFLOW_WRITE = "workflow:write"
    WORKFLOW_ADMIN = "workflow:admin"

    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"
    KNOWLEDGE_ADMIN = "knowledge:admin"

    MCP_READ = "mcp:read"
    MCP_WRITE = "mcp:write"
    MCP_ADMIN = "mcp:admin"

    AIRLOCK_READ = "airlock:read"
    AIRLOCK_WRITE = "airlock:write"
    AIRLOCK_ADMIN = "airlock:admin"

    INTEGRATION_READ = "integration:read"
    INTEGRATION_WRITE = "integration:write"
    INTEGRATION_ADMIN = "integration:admin"

    DEEPAGENT_READ = "deepagent:read"
    DEEPAGENT_WRITE = "deepagent:write"
    DEEPAGENT_ADMIN = "deepagent:admin"

    NOTIFICATION_READ = "notification:read"
    NOTIFICATION_WRITE = "notification:write"
    NOTIFICATION_ADMIN = "notification:admin"

    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"
    PROFILE_ADMIN = "profile:admin"

    SENTINEL_READ = "sentinel:read"
    SENTINEL_WRITE = "sentinel:write"
    SENTINEL_ADMIN = "sentinel:admin"

    TMS_READ = "tms:read"
    TMS_WRITE = "tms:write"
    TMS_ADMIN = "tms:admin"

    # Cross-tenant platform-admin model. Holders bypass the per-tenant filter
    # and trigger an elevated audit-log entry mirrored to the target tenant's
    # feed.
    PLATFORM_SUPPORT_READ = "platform:support:read"
    PLATFORM_SUPPORT_WRITE = "platform:support:write"


SUPER_WILDCARD: str = "*"
"""Held-side super-wildcard. Covers every required scope. Reserved for
break-glass / debug clients; never issue to end-user tokens in production."""


def scope_satisfies(required: str, held: Iterable[str]) -> bool:
    """Return ``True`` if ``held`` satisfies the ``required`` scope.

    See module docstring for the hierarchy rules. ``required`` is a literal
    scope string (no wildcards); ``held`` is the set of scopes the caller
    presents in their token. The function is allocation-free for typical
    inputs and safe to call on the request hot path.

    Empty ``required`` returns ``True`` (a no-op gate). An empty ``held``
    returns ``True`` iff ``required`` is empty.
    """
    if not required:
        return True

    # Materialize once. ``frozenset``/``set`` short-circuits.
    held_set: frozenset[str] = held if isinstance(held, frozenset) else frozenset(held)
    if not held_set:
        return False

    if SUPER_WILDCARD in held_set:
        return True
    if required in held_set:
        return True

    parts = required.split(":")
    if len(parts) < 2:
        # Single-segment scopes only match exactly or via super-wildcard.
        return False

    verb_wildcard = ":".join(parts[:-1]) + ":*"
    if verb_wildcard in held_set:
        return True

    namespace_wildcard = "*:" + ":".join(parts[1:])
    if namespace_wildcard in held_set:
        return True

    return False


def _all_known_scopes() -> frozenset[str]:
    """Internal helper: every scope value declared by :class:`Scope`.

    Used by tests and the optional CI lint that prevents string-literal
    scopes leaking into endpoint declarations.
    """
    return frozenset(s.value for s in Scope)


__all__ = ["SUPER_WILDCARD", "Scope", "scope_satisfies"]

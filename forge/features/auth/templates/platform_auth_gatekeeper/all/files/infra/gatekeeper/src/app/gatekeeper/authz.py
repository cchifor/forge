# src/app/gatekeeper/authz.py
"""Pure role-authorization primitives for the Gatekeeper.

This module deliberately imports **only the standard library** (no fastapi,
redis, weld, or opentelemetry) so it stays importable and unit-testable in
isolation — it holds the security-critical decision logic for the admin gate
in front of the ``/api/v1/api-keys`` lifecycle endpoints.

The two functions are pure (no I/O, no framework objects):

* :func:`extract_realm_roles` defensively pulls the Keycloak
  ``realm_access.roles`` list out of a verified access-token payload.
* :func:`is_authorized` answers "does this role set satisfy the required
  role" with an exact, case-sensitive string match.

Both fail closed: a malformed or missing claim yields an empty role list,
and an empty role list never satisfies a requirement.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extract_realm_roles(payload: Mapping[str, Any]) -> list[str]:
    """Read ``payload['realm_access']['roles']`` defensively.

    Returns a list of role-name strings. Any deviation from the expected
    shape — missing ``realm_access``, ``realm_access`` not a mapping,
    missing ``roles``, ``roles`` is ``None`` or not a list — collapses to
    an empty list so callers fail closed rather than crashing or
    accidentally iterating a non-list (e.g. a string yielding characters).

    Entries are coerced to ``str`` so the downstream exact-match comparison
    in :func:`is_authorized` is well-defined even for defensively-typed
    inputs.
    """
    if not isinstance(payload, Mapping):
        return []
    realm_access = payload.get("realm_access")
    if not isinstance(realm_access, Mapping):
        return []
    roles = realm_access.get("roles")
    if not isinstance(roles, list):
        return []
    return [str(role) for role in roles]


def is_authorized(roles: list[str], required_role: str) -> bool:
    """Return ``True`` iff *required_role* is present in *roles*.

    Exact, case-sensitive string match. An empty *roles* list never
    authorizes; a substring or differently-cased role does not satisfy the
    requirement (``"superadmin"`` does not grant ``"admin"``).
    """
    return required_role in roles


__all__ = ["extract_realm_roles", "is_authorized"]

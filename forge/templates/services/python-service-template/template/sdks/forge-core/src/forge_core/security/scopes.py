"""Generic, registry-free scope-hierarchy resolution.

Scopes follow a colon-delimited convention (``<namespace>:<verb>``) but this
module hardcodes *no* catalogue of services or verbs — it is the
Strive-decoupled generalisation of the platform's scope graph. Any
project-defined scope string works; the only structure assumed is the ``:``
delimiter for wildcard resolution.

Hierarchy rules consulted by :func:`scope_satisfies`:

1. Exact match — held set contains the required scope literally.
2. Super-wildcard — held set contains ``*`` (covers everything; reserved for
   break-glass / debug clients).
3. Verb wildcard — held set contains ``<prefix>:*`` where ``<prefix>`` is
   every segment of the required scope except the last. So ``orders:*``
   covers ``orders:read`` but NOT ``orders:admin:retry``.
4. Namespace wildcard — held set contains ``*:<tail>`` where ``<tail>`` is
   every segment except the first. ``*:read`` covers ``orders:read``.

Deeper wildcard combinations are intentionally not supported; their
authorization semantics are too easy to misread. Add explicit wildcards to
the token instead.
"""

from __future__ import annotations

from collections.abc import Iterable

SUPER_WILDCARD: str = "*"
"""Held-side super-wildcard. Covers every required scope. Reserved for
break-glass / debug clients; never issue to end-user tokens in production."""


def scope_satisfies(required: str, held: Iterable[str]) -> bool:
    """Return ``True`` if ``held`` satisfies the ``required`` scope.

    See module docstring for the hierarchy rules. ``required`` is a literal
    scope string (no wildcards); ``held`` is the set of scopes the caller
    presents in their token. Empty ``required`` returns ``True`` (a no-op
    gate); an empty ``held`` returns ``True`` iff ``required`` is empty.
    """
    if not required:
        return True

    held_set: frozenset[str] = held if isinstance(held, frozenset) else frozenset(held)
    if not held_set:
        return False

    if SUPER_WILDCARD in held_set:
        return True
    if required in held_set:
        return True

    parts = required.split(":")
    if len(parts) < 2:
        return False

    verb_wildcard = ":".join(parts[:-1]) + ":*"
    if verb_wildcard in held_set:
        return True

    namespace_wildcard = "*:" + ":".join(parts[1:])
    if namespace_wildcard in held_set:
        return True

    return False


__all__ = ["SUPER_WILDCARD", "scope_satisfies"]

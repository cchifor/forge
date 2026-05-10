# src/app/gatekeeper/scopes.py
"""Scope-string helpers used by the /auth/token endpoint.

These are deliberately thin: scope-hierarchy semantics live in
``platform_auth.scopes`` (which the backend AuthGuards use to authorize
inbound tokens). The gatekeeper side only needs to:

* Parse a space-delimited ``scope=`` form parameter into a set, per
  RFC 6749 §3.3.
* Compute the intersection of two scope sets, with ``None`` meaning
  "no constraint expressed" rather than "empty set".

The scope-mint pipeline applies these to compose ``effective_scopes``
from the registry's allowed set, the subject_token's scopes, and any
client-requested ``scope=`` form parameter — see
``service_token._mint_token_exchange``.
"""

from __future__ import annotations


def split_scope_string(value: str) -> frozenset[str]:
    """Parse a space-delimited scope string per RFC 6749 §3.3.

    Empty / whitespace-only input returns an empty set. Leading and
    trailing whitespace is tolerated; intermediate runs collapse the way
    ``str.split()`` does by default.
    """
    if not value:
        return frozenset()
    return frozenset(token for token in value.split() if token)


def scopes_intersection(
    granted: frozenset[str],
    requested: frozenset[str] | None,
) -> frozenset[str]:
    """Return ``granted`` constrained by ``requested`` if non-None.

    ``requested=None`` means the caller supplied no ``scope=`` form field
    — they implicitly accept whatever the registry grants. Passing an
    empty frozenset means "I asked for zero scopes" and yields empty.
    """
    if requested is None:
        return granted
    return granted & requested


__all__ = ["scopes_intersection", "split_scope_string"]

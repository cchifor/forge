"""The per-request caller-identity holder the persistence layer scopes against.

:class:`Account` is the small, mutable context object a request handler (or a
unit-of-work) carries to answer "who is calling, and within which tenant".
The generic repository / unit-of-work tenant- and owner-scope rows against
it; structurally it satisfies :class:`forge_core.persistence.AccountProtocol`
(``customer_id`` / ``user_id`` / ``is_admin()``).

It is intentionally framework-agnostic (stdlib only) and free of any one
product's governance model: an :class:`Account` knows its tenant, its user
and a coarse :class:`UserRole`, and nothing about platform-admin
super-powers, a fixed service-scope graph or tenant-suspension state. A
generating project that needs richer authorization layers that on top.
"""

from __future__ import annotations

import logging
from enum import StrEnum, auto
from uuid import UUID

_log = logging.getLogger(__name__)


class UserRole(StrEnum):
    """The coarse role an :class:`Account` carries.

    Only the generic trichotomy every service needs: a full-access
    ``ADMIN`` (owner-scoping is bypassed), a normal ``USER`` (owner-scoped),
    and a ``READ_ONLY`` principal. Finer-grained, product-specific roles are
    expressed by the generating project's own authorization layer, not here.
    """

    ADMIN = auto()
    USER = auto()
    READ_ONLY = auto()


def _to_uuid(value: str | UUID | None) -> UUID | None:
    """Coerce a string / UUID / ``None`` identity value into a ``UUID``.

    A non-UUID, non-empty value (e.g. a machine identity whose ``sub`` is a
    client-id rather than a UUID) is treated like the absence of the id —
    ``None`` — rather than raising, so service / machine callers degrade to
    "no user binding" instead of failing at construction. Downstream
    consumers of :attr:`Account.user_id` already handle ``None``.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        _log.debug("account._to_uuid: non-uuid value treated as None: %r", value)
        return None


class Account:
    """Per-request holder for the current user / tenant identity."""

    def __init__(
        self,
        customer_id: str | UUID | None,
        user_id: str | UUID | None,
        role: UserRole = UserRole.USER,
    ) -> None:
        self.customer_id: UUID | None = _to_uuid(customer_id)
        self.user_id: UUID | None = _to_uuid(user_id)
        self.role = role

    def is_admin(self) -> bool:
        """True when owner-scoping should be bypassed for this caller."""
        return self.role == UserRole.ADMIN

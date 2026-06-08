"""The structural account contract the persistence layer scopes against.

The generic repository / unit-of-work tenant- and owner-scope rows against a
*caller identity* — a customer (tenant) id, a user id, and an admin flag.
Rather than depend on any concrete identity model (forge ships one under
``forge_core.domain``; an application may bring its own), the persistence
layer depends only on this :class:`AccountProtocol` — a structural type any
object with the three members satisfies.

This is the seam that keeps ``forge_core.persistence`` free of the domain
package: the repository is generic over "something that looks like an
account", not over a specific class.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable


@runtime_checkable
class AccountProtocol(Protocol):
    """The caller-identity shape the persistence layer scopes against.

    * ``customer_id`` — the tenant the caller belongs to (``None`` ⇒ no
      tenant binding; tenant-scoped reads fall closed).
    * ``user_id`` — the acting user (``None`` ⇒ a service / machine identity;
      owner-scoping is skipped, only tenant-scoping applies).
    * ``is_admin()`` — when true, owner-scoping (``UserOwnedMixin``) is
      bypassed so an admin sees every row within the tenant.
    """

    customer_id: uuid.UUID | None
    user_id: uuid.UUID | None

    def is_admin(self) -> bool: ...

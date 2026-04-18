"""Base class for custom (non-AsyncBaseRepository) repositories that must
enforce tenant scoping on every read and write.

`AsyncBaseRepository` already tenant-filters via `_apply_scopes` when the
model mixes in `TenantMixin` / `UserOwnedMixin`. This base covers the
cases where the repository can't use `AsyncBaseRepository` — either the
relationship surface is richer than the generic repo handles (e.g.
Conversation → Messages → ToolCalls), or the table structure isn't a
simple single-model CRUD.

Every subclass receives a validated `Account`; missing tenant identity
raises `PermissionDeniedError` at construction time so a misconfigured
caller fails fast instead of silently reading cross-tenant data.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError
from service.domain.account import Account


class TenantScopedRepository:
    """Mixin-style base. Subclasses get `customer_id`, `user_id`, and
    `assert_owned()` for free, plus a guarantee that an unauthenticated
    caller cannot instantiate them.
    """

    def __init__(self, session: AsyncSession, account: Account) -> None:
        if account is None or account.customer_id is None or account.user_id is None:
            raise PermissionDeniedError(
                f"{type(self).__name__} requires an authenticated tenant "
                "(Account with both customer_id and user_id)."
            )
        self.session = session
        self._account = account
        self.customer_id: uuid.UUID = account.customer_id
        self.user_id: uuid.UUID = account.user_id

    def assert_owned(self, row: Any) -> None:
        """Raise `PermissionDeniedError` if `row.customer_id` doesn't match
        the caller. Use after fetching a row directly (by id) to avoid
        leaking another tenant's data through an unscoped query.
        """
        row_cid = getattr(row, "customer_id", None)
        if row_cid is None:
            raise PermissionDeniedError(
                f"{type(row).__name__} row has no customer_id; cannot assert ownership."
            )
        if row_cid != self.customer_id:
            raise PermissionDeniedError(
                f"{type(row).__name__} row belongs to another tenant."
            )

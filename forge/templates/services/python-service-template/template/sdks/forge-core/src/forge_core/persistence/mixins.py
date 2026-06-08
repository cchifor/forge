"""Declarative mixins for the common column patterns the repository scopes on.

These are plain SQLAlchemy declarative mixins — add them to a model's bases to
opt the model into the corresponding behaviour in
:class:`~forge_core.persistence.repository.AsyncBaseRepository`:

* :class:`TimestampMixin` — ``created_at`` / ``updated_at`` audit columns.
* :class:`TenantMixin` — a ``customer_id`` tenant discriminator; the repository
  filters reads/writes by it when constructed with an account.
* :class:`UserOwnedMixin` — a ``user_id`` ownership column; the repository
  narrows non-admin callers to their own rows.
* :class:`SoftDeleteMixin` — an ``is_active`` flag; the repository excludes
  inactive rows from reads and turns ``delete`` into a flag flip.

The tenant / owner columns are deliberately *generic*: an indexed, non-null
``Uuid`` with no foreign key to any particular accounts table and no
hardcoded "global tenant" sentinel. The application supplies the values (the
repository does so automatically from the account on ``create``).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Uuid, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class TenantMixin:
    """Adds an indexed ``customer_id`` tenant discriminator."""

    @declared_attr
    def customer_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, nullable=False, index=True)


class UserOwnedMixin:
    """Adds an indexed ``user_id`` ownership column."""

    @declared_attr
    def user_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, nullable=False, index=True)


class TimestampMixin:
    """Adds server-managed ``created_at`` / ``updated_at`` columns."""

    @declared_attr
    def created_at(cls) -> Mapped[datetime.datetime]:
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime.datetime]:
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )


class SoftDeleteMixin:
    """Adds an ``is_active`` flag for soft deletion."""

    @declared_attr
    def is_active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=True, nullable=False)

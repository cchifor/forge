"""SQLAlchemy declarative mixins exposed by weld-core (matrix-CI stub).

These match the real weld-core surface: each mixin contributes mapped
columns to any ORM model that inherits it.

* ``TenantMixin`` → ``customer_id`` UUID column (tenant scoping).
* ``UserOwnedMixin`` → ``user_id`` UUID column.
* ``TimestampMixin`` → ``created_at`` / ``updated_at`` datetime columns.

Models in the template (item.py, audit.py) reference these column
names in ``__table_args__`` indexes, so plain ``= None`` class attrs
aren't enough — the mixin has to register real SQLAlchemy columns.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """Tenant-scoped row — adds ``customer_id`` UUID column."""

    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)


class UserOwnedMixin:
    """Row owned by a specific user — adds ``user_id`` UUID column."""

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)


class TimestampMixin:
    """``created_at`` / ``updated_at`` timestamp columns."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

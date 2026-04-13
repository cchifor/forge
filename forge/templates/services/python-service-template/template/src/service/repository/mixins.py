import datetime
import uuid

from sqlalchemy import Boolean, DateTime, Uuid, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

GLOBAL_CUSTOMER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
GLOBAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def is_global_tenant(customer_id: uuid.UUID) -> bool:
    return customer_id == GLOBAL_CUSTOMER_ID


class TenantMixin:
    """Adds customer_id for multi-tenancy."""

    @declared_attr
    def customer_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, nullable=False, index=True, default=GLOBAL_CUSTOMER_ID)


class UserOwnedMixin:
    """Adds user_id for ownership tracking."""

    @declared_attr
    def user_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, nullable=False, index=True, default=GLOBAL_USER_ID)


class TimestampMixin:
    """Adds created_at and updated_at."""

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
    """Adds is_active for soft deletion."""

    @declared_attr
    def is_active(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=True, nullable=False)

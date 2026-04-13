from enum import StrEnum, auto
from uuid import UUID


class UserRole(StrEnum):
    ADMIN = auto()
    USER = auto()
    READ_ONLY = auto()


def _to_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


class Account:
    """Context holder for the current user/tenant (per-request)."""

    def __init__(
        self,
        customer_id: str | UUID | None,
        user_id: str | UUID | None,
        role: UserRole = UserRole.USER,
    ):
        self.customer_id: UUID | None = _to_uuid(customer_id)
        self.user_id: UUID | None = _to_uuid(user_id)
        self.role = role

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

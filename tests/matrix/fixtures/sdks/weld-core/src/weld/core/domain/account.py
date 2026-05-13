"""``weld.core.domain.account.Account`` — tenant account stub (matrix-CI).

Templates construct ``Account(customer_id=..., user_id=...)`` with
either UUID-shaped strings or actual ``uuid.UUID`` instances. The real
weld-core normalizes strings to UUIDs in __post_init__; this stub does
the same so ``mapped_column(Uuid)`` accepts the values without
``str has no attribute 'hex'``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


@dataclass
class Account:
    customer_id: Any = None
    user_id: Any = None
    id: Any = None
    name: str = ""
    email: str = ""
    roles: list[str] = field(default_factory=list)
    tenant_id: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attr in ("customer_id", "user_id", "id", "tenant_id"):
            raw = getattr(self, attr)
            coerced = _coerce_uuid(raw)
            if coerced is not None:
                setattr(self, attr, coerced)

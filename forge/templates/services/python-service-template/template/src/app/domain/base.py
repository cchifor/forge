from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class BaseDomainModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        frozen=True,
        use_enum_values=True,
    )


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    skip: int
    limit: int
    has_more: bool

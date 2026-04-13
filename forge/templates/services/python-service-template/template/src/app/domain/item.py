import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.base import BaseDomainModel, PaginatedResponse


class ItemStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: ItemStatus = ItemStatus.DRAFT


class ItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    tags: list[str] | None = None
    status: ItemStatus | None = None


class Item(BaseDomainModel):
    id: UUID
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: ItemStatus
    customer_id: UUID
    user_id: UUID
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class ItemSummary(BaseDomainModel):
    id: UUID
    name: str
    status: ItemStatus
    tags: list[str] = Field(default_factory=list)
    created_at: datetime.datetime | None = None


PaginatedItemResponse = PaginatedResponse[Item]

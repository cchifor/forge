# src/app/domain/realm.py
"""Domain models for Keycloak realms."""

from __future__ import annotations

import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.base import BaseDomainModel, PaginatedResponse


class RealmType(StrEnum):
    SHARED = "shared"
    DEDICATED = "dedicated"


class RealmCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_-]*$")
    realm_type: RealmType = RealmType.DEDICATED
    keycloak_base_url: str = Field(..., min_length=1, max_length=512)
    client_id: str = Field(..., min_length=1, max_length=255)
    client_secret: str = Field(..., min_length=1)
    max_tenants: int = Field(default=1, ge=1)
    is_active: bool = True


class RealmUpdate(BaseModel):
    keycloak_base_url: str | None = Field(None, max_length=512)
    client_id: str | None = Field(None, max_length=255)
    client_secret: str | None = None
    max_tenants: int | None = Field(None, ge=1)
    is_active: bool | None = None


class Realm(BaseDomainModel):
    id: UUID
    name: str
    realm_type: RealmType
    keycloak_base_url: str
    client_id: str
    client_secret: str  # encrypted at rest, decrypted for reads
    max_tenants: int
    is_active: bool
    tenant_count: int = 0
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class RealmSummary(BaseDomainModel):
    id: UUID
    name: str
    realm_type: RealmType
    is_active: bool
    tenant_count: int = 0


PaginatedRealmResponse = PaginatedResponse[Realm]

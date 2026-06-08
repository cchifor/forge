# src/app/domain/tenant.py
"""Domain models for tenants."""

from __future__ import annotations

import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.base import BaseDomainModel, PaginatedResponse


class TenantTier(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class TenantStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TenantCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(..., min_length=1, max_length=255)
    hostname: str = Field(..., min_length=1, max_length=255)
    admin_email: EmailStr = Field(..., max_length=255)
    tier: TenantTier = TenantTier.FREE
    rate_limit: int | None = None  # None → derived from tier defaults
    realm_id: UUID | None = None  # None → auto-assigned


class TenantUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=255)
    admin_email: str | None = Field(None, max_length=255)
    tier: TenantTier | None = None
    rate_limit: int | None = Field(None, ge=1, le=100000)
    realm_id: UUID | None = None
    status: TenantStatus | None = None
    keycloak_user_id: str | None = None
    provisioned_at: datetime.datetime | None = None


class Tenant(BaseDomainModel):
    id: UUID
    slug: str
    display_name: str
    hostname: str
    admin_email: str
    tier: TenantTier
    rate_limit: int
    status: TenantStatus
    realm_id: UUID
    keycloak_user_id: str | None = None
    provisioned_at: datetime.datetime | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None


class TenantSummary(BaseDomainModel):
    id: UUID
    slug: str
    display_name: str
    hostname: str
    tier: TenantTier
    status: TenantStatus


class TenantProvisionRequest(BaseModel):
    """Full provisioning request — creates realm (if needed), user, and Redis route."""

    slug: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z][a-z0-9-]*$")
    display_name: str = Field(..., min_length=1, max_length=255)
    hostname: str = Field(..., min_length=1, max_length=255)
    admin_email: EmailStr = Field(..., max_length=255)
    tier: TenantTier = TenantTier.FREE
    admin_password: str = Field(..., min_length=8)


class TenantRouteConfig(BaseModel):
    """Exact shape written to Redis for gatekeeper consumption."""

    tenant_id: str
    slug: str
    realm_type: str
    realm_name: str
    issuer_url: str
    client_id: str
    client_secret: str
    rate_limit: int


PaginatedTenantResponse = PaginatedResponse[Tenant]

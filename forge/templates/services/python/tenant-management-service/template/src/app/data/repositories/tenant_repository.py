# src/app/data/repositories/tenant_repository.py
"""Repository for Tenant entities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models.tenant import TenantModel
from app.domain.tenant import (
    Tenant,
    TenantCreate,
    TenantStatus,
    TenantTier,
    TenantUpdate,
)
from forge_core.persistence import AsyncBaseRepository


class TenantRepository(AsyncBaseRepository[TenantModel, Tenant, TenantCreate, TenantUpdate]):
    def __init__(self, session: AsyncSession, account: Any = None) -> None:
        super().__init__(
            session=session,
            model=TenantModel,
            schema=Tenant,
            account=account,
        )

    async def get_by_slug(self, slug: str) -> Tenant | None:
        query = select(TenantModel).where(TenantModel.slug == slug)
        result = await self.session.execute(query)
        obj = result.scalar_one_or_none()
        return self._to_schema(obj) if obj else None

    async def get_by_hostname(self, hostname: str) -> Tenant | None:
        query = select(TenantModel).where(TenantModel.hostname == hostname)
        result = await self.session.execute(query)
        obj = result.scalar_one_or_none()
        return self._to_schema(obj) if obj else None

    async def slug_exists(self, slug: str, exclude_id: Any = None) -> bool:
        query = select(TenantModel).where(TenantModel.slug == slug)
        if exclude_id is not None:
            query = query.where(TenantModel.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def hostname_exists(self, hostname: str, exclude_id: Any = None) -> bool:
        query = select(TenantModel).where(TenantModel.hostname == hostname)
        if exclude_id is not None:
            query = query.where(TenantModel.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def list_by_realm(self, realm_id: UUID) -> Sequence[Tenant]:
        query = (
            select(TenantModel)
            .where(TenantModel.realm_id == realm_id)
            .order_by(TenantModel.created_at.desc())
        )
        result = await self.session.execute(query)
        return [self._to_schema(obj) for obj in result.scalars().all()]

    async def list_active(self) -> Sequence[Tenant]:
        query = (
            select(TenantModel)
            .where(TenantModel.status == TenantStatus.ACTIVE)
            .order_by(TenantModel.created_at.desc())
        )
        result = await self.session.execute(query)
        return [self._to_schema(obj) for obj in result.scalars().all()]

    async def list_tenants(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        status: TenantStatus | None = None,
        tier: TenantTier | None = None,
        realm_id: UUID | None = None,
    ) -> Sequence[Tenant]:
        query = select(TenantModel)
        if status:
            query = query.where(TenantModel.status == status)
        if tier:
            query = query.where(TenantModel.tier == tier)
        if realm_id:
            query = query.where(TenantModel.realm_id == realm_id)
        query = query.order_by(TenantModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return [self._to_schema(obj) for obj in result.scalars().all()]

    async def count_tenants(
        self,
        *,
        status: TenantStatus | None = None,
        tier: TenantTier | None = None,
        realm_id: UUID | None = None,
    ) -> int:
        query = select(func.count()).select_from(TenantModel)
        if status:
            query = query.where(TenantModel.status == status)
        if tier:
            query = query.where(TenantModel.tier == tier)
        if realm_id:
            query = query.where(TenantModel.realm_id == realm_id)
        result = await self.session.execute(query)
        return result.scalar_one()

# src/app/data/repositories/realm_repository.py
"""Repository for Realm entities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models.realm import RealmModel
from app.domain.realm import Realm, RealmCreate, RealmType, RealmUpdate
from app.domain.tenant import TenantStatus
from forge_core.persistence import AsyncBaseRepository


class RealmRepository(AsyncBaseRepository[RealmModel, Realm, RealmCreate, RealmUpdate]):
    def __init__(self, session: AsyncSession, account: Any = None) -> None:
        super().__init__(
            session=session,
            model=RealmModel,
            schema=Realm,
            account=account,
        )

    async def get_by_name(self, name: str) -> Realm | None:
        query = select(RealmModel).where(RealmModel.name == name)
        result = await self.session.execute(query)
        obj = result.scalar_one_or_none()
        return self._to_schema(obj) if obj else None

    async def name_exists(self, name: str, exclude_id: Any = None) -> bool:
        query = select(RealmModel).where(RealmModel.name == name)
        if exclude_id is not None:
            query = query.where(RealmModel.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

    async def get_shared_with_capacity(self) -> Realm | None:
        """Find a shared realm that hasn't reached max_tenants."""
        from app.data.models.tenant import TenantModel

        subq = (
            select(func.count(TenantModel.id))
            .where(TenantModel.realm_id == RealmModel.id)
            .where(TenantModel.status != TenantStatus.DELETED)
            .correlate(RealmModel)
            .scalar_subquery()
        )
        query = (
            select(RealmModel)
            .where(RealmModel.realm_type == RealmType.SHARED)
            .where(RealmModel.is_active.is_(True))
            .where(subq < RealmModel.max_tenants)
            .limit(1)
        )
        result = await self.session.execute(query)
        obj = result.scalar_one_or_none()
        return self._to_schema(obj) if obj else None

    async def list_realms(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        realm_type: RealmType | None = None,
    ) -> Sequence[Realm]:
        query = select(RealmModel)
        if realm_type:
            query = query.where(RealmModel.realm_type == realm_type)
        query = query.order_by(RealmModel.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return [self._to_schema(obj) for obj in result.scalars().all()]

    async def count_realms(self, *, realm_type: RealmType | None = None) -> int:
        query = select(func.count()).select_from(RealmModel)
        if realm_type:
            query = query.where(RealmModel.realm_type == realm_type)
        result = await self.session.execute(query)
        return result.scalar_one()

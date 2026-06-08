# src/app/services/realm_service.py
"""Business logic for realm management."""

from __future__ import annotations

from uuid import UUID

from app.core.errors import AlreadyExistsError, ApplicationError, NotFoundError
from app.data.repositories.realm_repository import RealmRepository
from app.data.repositories.tenant_repository import TenantRepository
from app.domain.realm import (
    PaginatedRealmResponse,
    Realm,
    RealmCreate,
    RealmType,
    RealmUpdate,
)
from app.domain.tenant import TenantStatus
from forge_core.persistence import AsyncUnitOfWork


class RealmService:
    def __init__(self, uow: AsyncUnitOfWork) -> None:
        self._uow = uow

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        realm_type: RealmType | None = None,
    ) -> PaginatedRealmResponse:
        async with self._uow as uow:
            repo = uow.repo(RealmRepository)
            realms = await repo.list_realms(skip=skip, limit=limit, realm_type=realm_type)
            total = await repo.count_realms(realm_type=realm_type)
        return PaginatedRealmResponse(
            items=list(realms),
            total=total,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total,
        )

    async def get(self, realm_id: UUID) -> Realm:
        async with self._uow as uow:
            repo = uow.repo(RealmRepository)
            realm = await repo.get(realm_id)
        if not realm:
            raise NotFoundError("Realm", realm_id)
        return realm

    async def get_by_name(self, name: str) -> Realm | None:
        async with self._uow as uow:
            repo = uow.repo(RealmRepository)
            return await repo.get_by_name(name)

    async def create(self, data: RealmCreate) -> Realm:
        async with self._uow as uow:
            repo = uow.repo(RealmRepository)
            if await repo.name_exists(data.name):
                raise AlreadyExistsError("Realm", data.name)
            realm = await repo.create(data)
        return realm

    async def update(self, realm_id: UUID, data: RealmUpdate) -> Realm:
        async with self._uow as uow:
            repo = uow.repo(RealmRepository)
            existing = await repo.get(realm_id)
            if not existing:
                raise NotFoundError("Realm", realm_id)
            realm = await repo.update(realm_id, data)
        return realm

    async def delete(self, realm_id: UUID) -> None:
        async with self._uow as uow:
            repo = uow.repo(RealmRepository)
            existing = await repo.get(realm_id)
            if not existing:
                raise NotFoundError("Realm", realm_id)
            # Guard: cannot delete a realm with active tenants
            tenant_repo = uow.repo(TenantRepository)
            tenants = await tenant_repo.list_by_realm(realm_id)
            active = [t for t in tenants if t.status != TenantStatus.DELETED]
            if active:
                raise ApplicationError(
                    f"Cannot delete realm '{existing.name}' with {len(active)} active tenant(s)"
                )
            await repo.delete(realm_id)

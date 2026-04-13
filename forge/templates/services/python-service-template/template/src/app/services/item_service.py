import logging
from uuid import UUID

from app.core.errors import AlreadyExistsError, NotFoundError
from app.data.repositories.item_repository import ItemRepository
from app.domain.item import (
    Item,
    ItemCreate,
    ItemStatus,
    ItemUpdate,
    PaginatedItemResponse,
)
from service.uow.aio import AsyncUnitOfWork

logger = logging.getLogger(__name__)


class ItemService:
    def __init__(self, uow: AsyncUnitOfWork):
        self._uow = uow

    async def list(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        status: ItemStatus | None = None,
        search: str | None = None,
    ) -> PaginatedItemResponse:
        async with self._uow as uow:
            repo = uow.repo(ItemRepository)
            items = await repo.list_items(skip=skip, limit=limit, status=status, search=search)
            total = await repo.count_items(status=status, search=search)

        return PaginatedItemResponse(
            items=list(items),
            total=total,
            skip=skip,
            limit=limit,
            has_more=(skip + limit) < total,
        )

    async def get(self, item_id: UUID) -> Item:
        async with self._uow as uow:
            repo = uow.repo(ItemRepository)
            item = await repo.get(item_id)
        if not item:
            raise NotFoundError("Item", item_id)
        return item

    async def create(self, data: ItemCreate) -> Item:
        async with self._uow as uow:
            repo = uow.repo(ItemRepository)
            if await repo.name_exists(data.name):
                raise AlreadyExistsError("Item", data.name)
            item = await repo.create(data)
        return item

    async def update(self, item_id: UUID, data: ItemUpdate) -> Item:
        async with self._uow as uow:
            repo = uow.repo(ItemRepository)
            existing = await repo.get(item_id)
            if not existing:
                raise NotFoundError("Item", item_id)
            if data.name and data.name != existing.name:
                if await repo.name_exists(data.name, exclude_id=item_id):
                    raise AlreadyExistsError("Item", data.name)
            item = await repo.update(item_id, data)
        return item

    async def delete(self, item_id: UUID) -> None:
        async with self._uow as uow:
            repo = uow.repo(ItemRepository)
            existing = await repo.get(item_id)
            if not existing:
                raise NotFoundError("Item", item_id)
            await repo.delete(item_id)

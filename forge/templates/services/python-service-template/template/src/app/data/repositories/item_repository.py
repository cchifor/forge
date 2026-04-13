from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.models.item import ItemModel
from app.domain.item import Item, ItemCreate, ItemStatus, ItemUpdate
from service.domain.account import Account
from service.repository.aio import AsyncBaseRepository


class ItemRepository(AsyncBaseRepository[ItemModel, Item, ItemCreate, ItemUpdate]):
    def __init__(self, session: AsyncSession, account: Account | None = None):
        super().__init__(
            session=session,
            model=ItemModel,
            schema=Item,
            account=account,
        )

    async def list_items(
        self,
        *,
        skip: int = 0,
        limit: int = 50,
        status: ItemStatus | None = None,
        search: str | None = None,
        tags: list[str] | None = None,
        sort_by: list[str] | None = None,
    ) -> Sequence[Item]:
        query = self._get_base_query()

        if status:
            query = query.where(ItemModel.status == status)

        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    ItemModel.name.ilike(pattern),
                    ItemModel.description.ilike(pattern),
                )
            )

        query = self._apply_sorting(query, sort_by)
        query = query.offset(skip).limit(limit)

        result = await self.session.execute(query)
        return [self._to_schema(obj) for obj in result.scalars().all()]

    async def count_items(
        self,
        *,
        status: ItemStatus | None = None,
        search: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(ItemModel)
        query = self._apply_scopes(query)

        if status:
            query = query.where(ItemModel.status == status)

        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    ItemModel.name.ilike(pattern),
                    ItemModel.description.ilike(pattern),
                )
            )

        result = await self.session.execute(query)
        return result.scalar_one()

    async def name_exists(self, name: str, exclude_id: Any = None) -> bool:
        query = self._get_base_query().where(ItemModel.name == name)
        if exclude_id is not None:
            query = query.where(ItemModel.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None

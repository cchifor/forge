from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.base import ExecutableOption

from service.domain.account import Account
from service.repository.errors import EntityNotFoundException, RepositoryException

from .base import MAX_PAGE_SIZE, RepositoryLogicMixin
from .mixins import SoftDeleteMixin, TenantMixin, UserOwnedMixin

ModelType = TypeVar("ModelType", bound=DeclarativeBase)
PydanticSchema = TypeVar("PydanticSchema", bound=BaseModel)
CreateSchema = TypeVar("CreateSchema", bound=BaseModel)
UpdateSchema = TypeVar("UpdateSchema", bound=BaseModel)


class AsyncBaseRepository(
    RepositoryLogicMixin[ModelType],
    Generic[ModelType, PydanticSchema, CreateSchema, UpdateSchema],
):
    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelType],
        schema: type[PydanticSchema],
        account: Account | None = None,
    ):
        self.session = session
        self.schema = schema
        self._init_logic(model, account)

    def _to_schema(self, db_obj: ModelType) -> PydanticSchema:
        try:
            return self.schema.model_validate(self._orm_to_dict(db_obj))
        except ValidationError as e:
            raise RepositoryException(
                f"Schema validation failed mapping {self.model.__name__} "
                f"\u2192 {self.schema.__name__}: {e}"
            ) from e

    async def get(
        self, id: Any, options: Sequence[ExecutableOption] | None = None
    ) -> PydanticSchema | None:
        query = self._get_base_query().where(getattr(self.model, self.pk_name) == id)
        if options:
            query = query.options(*options)
        result = await self.session.execute(query)
        db_obj = result.scalar_one_or_none()
        return self._to_schema(db_obj) if db_obj else None

    async def get_or_fail(
        self, id: Any, options: Sequence[ExecutableOption] | None = None
    ) -> PydanticSchema:
        obj = await self.get(id, options=options)
        if not obj:
            raise EntityNotFoundException(self.model.__name__, id)
        return obj

    async def get_by(
        self,
        *,
        options: Sequence[ExecutableOption] | None = None,
        **kwargs: Any,
    ) -> PydanticSchema | None:
        self._validate_filter_keys(kwargs)
        query = self._get_base_query()
        for field, value in kwargs.items():
            query = query.where(getattr(self.model, field) == value)
        if options:
            query = query.options(*options)
        query = query.limit(1)
        try:
            result = await self.session.execute(query)
            db_obj = result.scalar_one_or_none()
        except SQLAlchemyError as e:
            raise RepositoryException(f"Database error during get_by: {str(e)}") from e
        return self._to_schema(db_obj) if db_obj else None

    async def get_all(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        sort_by: list[str] | None = None,
        options: Sequence[ExecutableOption] | None = None,
    ) -> Sequence[PydanticSchema]:
        limit = min(limit, MAX_PAGE_SIZE)
        query = self._get_base_query()
        query = self._apply_filtering(query, filters)
        query = self._apply_sorting(query, sort_by)
        if options:
            query = query.options(*options)
        query = query.offset(skip).limit(limit)
        try:
            result = await self.session.execute(query)
            return [self._to_schema(obj) for obj in result.scalars().all()]
        except SQLAlchemyError as e:
            raise RepositoryException(f"Database error during fetch: {str(e)}") from e

    async def count(self, *, filters: dict[str, Any] | None = None) -> int:
        query = select(func.count()).select_from(self.model)
        query = self._apply_scopes(query)
        query = self._apply_filtering(query, filters)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def exists(self, id: Any) -> bool:
        query = (
            select(func.count())
            .select_from(self.model)
            .where(getattr(self.model, self.pk_name) == id)
        )
        query = self._apply_scopes(query)
        result = await self.session.execute(query)
        return result.scalar_one() > 0

    async def create(self, obj_in: CreateSchema, **kwargs: Any) -> PydanticSchema:
        obj_data = obj_in.model_dump()
        if self.account:
            if issubclass(self.model, TenantMixin):
                obj_data["customer_id"] = self.account.customer_id
            if issubclass(self.model, UserOwnedMixin):
                obj_data["user_id"] = self.account.user_id
        obj_data.update(kwargs)
        obj_data = {
            k: v
            for k, v in obj_data.items()
            if k in self._column_keys and not (k == self.pk_name and v is None)
        }
        db_obj = self.model(**obj_data)
        self.session.add(db_obj)
        try:
            await self.session.flush()
            await self.session.refresh(db_obj)
        except IntegrityError as e:
            raise RepositoryException(f"Integrity error: {e.orig}") from e
        except SQLAlchemyError as e:
            raise RepositoryException(f"Database error: {str(e)}") from e
        return self._to_schema(db_obj)

    async def update(self, id: Any, obj_in: UpdateSchema) -> PydanticSchema:
        query = self._get_base_query().where(getattr(self.model, self.pk_name) == id)
        result = await self.session.execute(query)
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            raise EntityNotFoundException(self.model.__name__, id)
        update_data = obj_in.model_dump(exclude_unset=True)
        self._sanitize_update_data(update_data)
        update_data = self._prepare_update_data(db_obj, update_data)
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        self.session.add(db_obj)
        try:
            await self.session.flush()
            await self.session.refresh(db_obj)
        except IntegrityError as e:
            raise RepositoryException(f"Integrity error: {e.orig}") from e
        except SQLAlchemyError as e:
            raise RepositoryException(f"Database error: {str(e)}") from e
        return self._to_schema(db_obj)

    async def delete(self, id: Any) -> None:
        query = self._get_base_query().where(getattr(self.model, self.pk_name) == id)
        result = await self.session.execute(query)
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            raise EntityNotFoundException(self.model.__name__, id)
        if issubclass(self.model, SoftDeleteMixin):
            db_obj.is_active = False  # type: ignore
            self.session.add(db_obj)
        else:
            await self.session.delete(db_obj)
        try:
            await self.session.flush()
        except SQLAlchemyError as e:
            raise RepositoryException(f"Database error during delete: {str(e)}") from e

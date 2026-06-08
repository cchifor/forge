"""The generic async CRUD repository and its query-building logic.

:class:`AsyncBaseRepository` is a generic repository over a SQLAlchemy
declarative model and a set of pydantic schemas: it introspects the model's
columns / primary key, applies tenant + owner + soft-delete *scopes* derived
from the mixins the model opts into, and exposes ``get`` / ``get_all`` /
``count`` / ``create`` / ``update`` / ``delete`` returning validated pydantic
schemas rather than ORM rows.

Scoping is driven by the optional :class:`~forge_core.persistence.account.AccountProtocol`
the repository is constructed with — there is no dependency on any concrete
identity model. Errors are raised from :mod:`forge_core.errors` (the same
hierarchy the rest of a forge service uses), so callers catch one error tree.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import asc, desc, false, func, inspect, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, InstanceState, Mapper
from sqlalchemy.sql.base import ExecutableOption
from sqlalchemy.sql.selectable import Select

from forge_core.errors import NotFoundError, RepositoryError
from forge_core.persistence.account import AccountProtocol
from forge_core.persistence.mixins import SoftDeleteMixin, TenantMixin, UserOwnedMixin

# Cap on a single page of results, defending the DB from an unbounded fetch.
MAX_PAGE_SIZE = 1000

# Type parameters (PEP 484 form so the package stays importable on the declared
# Python 3.11 floor; PEP 695 ``class C[T]`` syntax is 3.12+).
ModelType = TypeVar("ModelType", bound=DeclarativeBase)
PydanticSchema = TypeVar("PydanticSchema", bound=BaseModel)
CreateSchema = TypeVar("CreateSchema", bound=BaseModel)
UpdateSchema = TypeVar("UpdateSchema", bound=BaseModel)


class RepositoryLogicMixin(Generic[ModelType]):
    """Shared logic for repositories: introspection, scoping, filtering, sorting."""

    model: type[ModelType]
    account: AccountProtocol | None
    mapper: Mapper
    pk_name: str
    _valid_columns: set[str]
    _column_keys: set[str]

    def _init_logic(self, model: type[ModelType], account: AccountProtocol | None) -> None:
        self.model = model
        self.account = account
        self.mapper = cast(Mapper, inspect(self.model))
        self.pk_name = self._get_primary_key_name()
        self._valid_columns = {c.key for c in self.mapper.attrs}
        self._column_keys = {c.key for c in self.mapper.column_attrs}

    def _get_primary_key_name(self) -> str:
        primary_keys = self.mapper.primary_key
        if not primary_keys:
            raise RepositoryError(f"Model {self.model.__name__} has no primary key.")
        pks_list = list(primary_keys)
        if len(pks_list) > 1:
            raise NotImplementedError(f"Composite PKs not supported for {self.model.__name__}.")
        return pks_list[0].name

    def _apply_scopes(self, query: Select) -> Select:
        if issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.is_active.is_(True))

        if not self.account:
            return query

        if issubclass(self.model, TenantMixin):
            if self.account.customer_id is None:
                # No tenant binding ⇒ fall closed (no rows) rather than leak
                # across tenants.
                return query.where(false())
            query = query.where(self.model.customer_id == self.account.customer_id)

        if issubclass(self.model, UserOwnedMixin):
            if not self.account.is_admin() and self.account.user_id is not None:
                query = query.where(self.model.user_id == self.account.user_id)
            # ``user_id is None`` is a service / machine identity: the tenant
            # filter above is the right scope; narrowing by user_id would hide
            # every row from the service.

        return query

    def _get_base_query(self) -> Select:
        return self._apply_scopes(select(self.model))

    def _sanitize_update_data(self, update_data: dict[str, Any]) -> None:
        update_data.pop(self.pk_name, None)
        if issubclass(self.model, TenantMixin):
            update_data.pop("customer_id", None)
        if issubclass(self.model, UserOwnedMixin):
            update_data.pop("user_id", None)

    def _apply_filtering(self, query: Select, filters: dict[str, Any] | None) -> Select:
        if not filters:
            return query
        self._validate_filter_keys(filters)
        for field, value in filters.items():
            col_attr = getattr(self.model, field)
            if isinstance(value, list | tuple):
                query = query.where(col_attr.in_(value))
            else:
                query = query.where(col_attr == value)
        return query

    def _apply_sorting(self, query: Select, sort_by: list[str] | None) -> Select:
        if sort_by:
            for field_name in sort_by:
                direction = desc if field_name.startswith("-") else asc
                clean_field = field_name.lstrip("-")
                if clean_field in self._valid_columns:
                    query = query.order_by(direction(getattr(self.model, clean_field)))
        else:
            query = query.order_by(desc(getattr(self.model, self.pk_name)))
        return query

    def _validate_filter_keys(self, kwargs: dict[str, Any]) -> None:
        for field in kwargs:
            if field not in self._valid_columns:
                raise RepositoryError(
                    f"Invalid filter column '{field}' for model {self.model.__name__}"
                )

    def _prepare_update_data(
        self, db_obj: ModelType, update_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Hook: transform the validated update payload before it's applied."""
        return update_data

    @staticmethod
    def _orm_to_dict(db_obj: DeclarativeBase) -> dict[str, Any]:
        state: InstanceState = inspect(db_obj)  # type: ignore[assignment]
        mapper: Mapper = state.mapper
        data: dict[str, Any] = {c.key: getattr(db_obj, c.key) for c in mapper.column_attrs}
        for rel in mapper.relationships:
            if rel.key not in state.dict:
                continue
            value = state.dict[rel.key]
            if isinstance(value, list):
                data[rel.key] = [RepositoryLogicMixin._orm_to_dict(item) for item in value]
            elif value is not None:
                data[rel.key] = RepositoryLogicMixin._orm_to_dict(value)
            else:
                data[rel.key] = None
        return data


class AsyncBaseRepository(
    RepositoryLogicMixin[ModelType],
    Generic[ModelType, PydanticSchema, CreateSchema, UpdateSchema],
):
    """Generic async CRUD repository returning validated pydantic schemas."""

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelType],
        schema: type[PydanticSchema],
        account: AccountProtocol | None = None,
    ) -> None:
        self.session = session
        self.schema = schema
        self._init_logic(model, account)

    def _to_schema(self, db_obj: ModelType) -> PydanticSchema:
        try:
            return self.schema.model_validate(self._orm_to_dict(db_obj))
        except PydanticValidationError as e:
            raise RepositoryError(
                f"Schema validation failed mapping {self.model.__name__} "
                f"→ {self.schema.__name__}: {e}"
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
            raise NotFoundError(self.model.__name__, id)
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
            raise RepositoryError(f"Database error during get_by: {e}") from e
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
            raise RepositoryError(f"Database error during fetch: {e}") from e

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
            raise RepositoryError(f"Integrity error: {e.orig}") from e
        except SQLAlchemyError as e:
            raise RepositoryError(f"Database error: {e}") from e
        return self._to_schema(db_obj)

    async def update(self, id: Any, obj_in: UpdateSchema) -> PydanticSchema:
        query = self._get_base_query().where(getattr(self.model, self.pk_name) == id)
        result = await self.session.execute(query)
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            raise NotFoundError(self.model.__name__, id)
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
            raise RepositoryError(f"Integrity error: {e.orig}") from e
        except SQLAlchemyError as e:
            raise RepositoryError(f"Database error: {e}") from e
        return self._to_schema(db_obj)

    async def delete(self, id: Any) -> None:
        query = self._get_base_query().where(getattr(self.model, self.pk_name) == id)
        result = await self.session.execute(query)
        db_obj = result.scalar_one_or_none()
        if not db_obj:
            raise NotFoundError(self.model.__name__, id)
        if issubclass(self.model, SoftDeleteMixin):
            db_obj.is_active = False
            self.session.add(db_obj)
        else:
            await self.session.delete(db_obj)
        try:
            await self.session.flush()
        except SQLAlchemyError as e:
            raise RepositoryError(f"Database error during delete: {e}") from e

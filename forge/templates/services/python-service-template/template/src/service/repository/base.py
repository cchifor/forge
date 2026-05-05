from typing import Any, Generic, TypeVar, cast

from sqlalchemy import asc, desc, false, inspect, select
from sqlalchemy.orm import DeclarativeBase, InstanceState, Mapper
from sqlalchemy.sql.selectable import Select

from service.domain.account import Account
from service.repository.errors import RepositoryException
from service.repository.mixins import SoftDeleteMixin, TenantMixin, UserOwnedMixin

MAX_PAGE_SIZE = 1000

ModelType = TypeVar("ModelType", bound=DeclarativeBase)


class RepositoryLogicMixin(Generic[ModelType]):
    """Shared business logic for repositories: introspection, scoping, filtering, sorting."""

    model: type[ModelType]
    account: Account | None
    mapper: Mapper
    pk_name: str
    _valid_columns: set[str]
    _column_keys: set[str]

    def _init_logic(self, model: type[ModelType], account: Account | None) -> None:
        self.model = model
        self.account = account
        self.mapper = cast(Mapper, inspect(self.model))
        self.pk_name = self._get_primary_key_name()
        self._valid_columns = {c.key for c in self.mapper.attrs}
        self._column_keys = {c.key for c in self.mapper.column_attrs}

    def _get_primary_key_name(self) -> str:
        primary_keys = self.mapper.primary_key
        if not primary_keys:
            raise RepositoryException(f"Model {self.model.__name__} has no primary key.")
        pks_list = list(primary_keys)
        if len(pks_list) > 1:
            raise NotImplementedError(f"Composite PKs not supported for {self.model.__name__}.")
        return pks_list[0].name

    def _apply_scopes(self, query: Select) -> Select:
        if issubclass(self.model, SoftDeleteMixin):
            query = query.where(self.model.is_active.is_(True))  # type: ignore

        if not self.account:
            return query

        if issubclass(self.model, TenantMixin):
            if self.account.customer_id is None:
                return query.where(false())
            query = query.where(self.model.customer_id == self.account.customer_id)  # type: ignore

        if issubclass(self.model, UserOwnedMixin):
            if not self.account.is_admin():
                if self.account.user_id is None:
                    return query.where(false())
                query = query.where(self.model.user_id == self.account.user_id)  # type: ignore

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
            if isinstance(value, (list, tuple)):
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
                raise RepositoryException(
                    f"Invalid filter column '{field}' for model {self.model.__name__}"
                )

    def _prepare_update_data(
        self, db_obj: ModelType, update_data: dict[str, Any]
    ) -> dict[str, Any]:
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

"""``weld.core.persistence.repository.aio.AsyncBaseRepository`` — async ORM base (matrix-CI stub).

The template's ``ItemRepository`` extends with four type parameters and
calls into the base for: query construction (``_get_base_query``),
tenant scoping (``_apply_scopes``), sort handling (``_apply_sorting``),
ORM↔schema mapping (``_to_schema``), plus the standard CRUD verbs.

This stub provides enough behavior to keep the template's unit tests
green when running against ``sqlite+aiosqlite``:

* ``__init__`` accepts ``session, model, schema, account`` (the four
  keyword args the template's repos pass) and stores them.
* ``_get_base_query`` returns ``select(model)`` with tenant scopes
  applied.
* ``_apply_scopes`` filters by ``customer_id`` when an account is
  attached (no-op otherwise — keeps the no-account tests working).
* ``_apply_sorting`` accepts a ``["field", "-field"]`` list and emits
  the matching ``order_by``.
* ``_to_schema`` uses Pydantic v2's ``model_validate(obj,
  from_attributes=True)`` to convert ORM rows.
* CRUD methods (``get``, ``list``, ``create``, ``update``, ``delete``)
  are working passthroughs against the session.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import delete as sa_delete, select

ModelT = TypeVar("ModelT")
EntityT = TypeVar("EntityT")
CreateT = TypeVar("CreateT")
UpdateT = TypeVar("UpdateT")


class AsyncBaseRepository(Generic[ModelT, EntityT, CreateT, UpdateT]):
    def __init__(
        self,
        *args: Any,
        session: Any = None,
        model: Any = None,
        schema: Any = None,
        account: Any = None,
        **kwargs: Any,
    ) -> None:
        self.session = session
        self.model = model
        self.schema = schema
        self.account = account

    def _get_base_query(self) -> Any:
        return self._apply_scopes(select(self.model))

    def _apply_scopes(self, query: Any) -> Any:
        if self.account is None or self.model is None:
            return query
        customer_id = getattr(self.account, "customer_id", None)
        if customer_id and hasattr(self.model, "customer_id"):
            query = query.where(self.model.customer_id == customer_id)
        return query

    def _apply_sorting(self, query: Any, sort_by: list[str] | None) -> Any:
        if not sort_by or self.model is None:
            return query
        for raw in sort_by:
            direction = "asc"
            col_name = raw
            if raw.startswith("-"):
                direction = "desc"
                col_name = raw[1:]
            col = getattr(self.model, col_name, None)
            if col is None:
                continue
            query = query.order_by(col.desc() if direction == "desc" else col.asc())
        return query

    def _to_schema(self, obj: Any) -> Any:
        if obj is None or self.schema is None:
            return obj
        if hasattr(self.schema, "model_validate"):
            return self.schema.model_validate(obj, from_attributes=True)
        if hasattr(self.schema, "from_orm"):
            return self.schema.from_orm(obj)
        return obj

    async def get(self, id: Any) -> EntityT | None:
        query = self._get_base_query().where(self.model.id == id)
        result = await self.session.execute(query)
        obj = result.scalar_one_or_none()
        return self._to_schema(obj) if obj is not None else None

    async def list(
        self, *, skip: int = 0, limit: int = 50, **kwargs: Any
    ) -> list[EntityT]:
        query = self._get_base_query().offset(skip).limit(limit)
        result = await self.session.execute(query)
        return [self._to_schema(obj) for obj in result.scalars().all()]

    async def create(self, data: CreateT) -> EntityT:
        payload: dict[str, Any]
        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        elif isinstance(data, dict):
            payload = dict(data)
        else:
            payload = dict(getattr(data, "__dict__", {}))
        if self.account is not None and hasattr(self.model, "customer_id"):
            payload.setdefault("customer_id", getattr(self.account, "customer_id", None))
        if self.account is not None and hasattr(self.model, "user_id"):
            payload.setdefault("user_id", getattr(self.account, "user_id", None))
        obj = self.model(**payload)
        self.session.add(obj)
        await self.session.flush()
        return self._to_schema(obj)

    async def update(self, id: Any, data: UpdateT) -> EntityT | None:
        result = await self.session.execute(
            self._get_base_query().where(self.model.id == id)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            return None
        payload: dict[str, Any]
        if hasattr(data, "model_dump"):
            payload = data.model_dump(exclude_unset=True)
        elif isinstance(data, dict):
            payload = dict(data)
        else:
            payload = dict(getattr(data, "__dict__", {}))
        for key, value in payload.items():
            setattr(obj, key, value)
        await self.session.flush()
        return self._to_schema(obj)

    async def delete(self, id: Any) -> None:
        query = sa_delete(self.model).where(self.model.id == id)
        if self.account is not None and hasattr(self.model, "customer_id"):
            customer_id = getattr(self.account, "customer_id", None)
            if customer_id:
                query = query.where(self.model.customer_id == customer_id)
        await self.session.execute(query)

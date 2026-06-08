"""Dynamic filter dependencies from a Pydantic model.

Given a Pydantic model describing filter fields, build a FastAPI dependency
that exposes each field as an optional query parameter. Usage::

    class ItemFilter(BaseModel):
        status: ItemStatus | None = None
        search: str | None = None

    @router.get("/items")
    async def list_items(
        filters: ItemFilter = Depends(filter_dependency(ItemFilter)),
    ):
        repo_filters = to_repo_filters(filters)
        ...

Targets Python 3.11 — uses ``TypeVar`` rather than the 3.12 ``[T]`` syntax.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def filter_dependency(model: type[T]) -> Callable[..., T]:
    """Create a FastAPI dependency that extracts filter fields from query params.

    Every field of ``model`` becomes an optional query parameter; only the
    values the client actually provided (non-``None``) are passed to the model,
    so unset filters fall back to the model's own defaults. Returns a callable
    suitable for ``Depends()``.
    """

    def _dependency(**kwargs: Any) -> T:
        provided = {k: v for k, v in kwargs.items() if v is not None}
        return model(**provided)

    params = []
    for field_name, field_info in model.model_fields.items():
        annotation = field_info.annotation
        default = Query(None, description=field_info.description or field_name)
        params.append(
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation | None,
            )
        )

    _dependency.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    return _dependency


def to_repo_filters(model: BaseModel) -> dict[str, Any]:
    """Convert a filter model to a dict for a repository ``filters`` param.

    Only includes fields that were explicitly set (non-``None``).
    """
    return {k: v for k, v in model.model_dump().items() if v is not None}


__all__ = ["filter_dependency", "to_repo_filters"]

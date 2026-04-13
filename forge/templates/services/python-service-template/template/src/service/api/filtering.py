"""Dynamic filter generation from Pydantic models.

Given a Pydantic model describing filter fields, auto-generates a FastAPI
dependency that extracts those fields from query params.

Usage::

    class ItemFilter(BaseModel):
        status: ItemStatus | None = None
        search: str | None = None
        tags: list[str] | None = None

    @router.get("/items")
    async def list_items(
        filters: ItemFilter = Depends(filter_dependency(ItemFilter)),
    ):
        ...
"""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def filter_dependency(model: type[T]):
    """Create a FastAPI dependency that extracts filter fields from query params.

    All fields of the model become optional query parameters. Only non-None
    values are included in the resulting model instance.

    Returns a dependency function suitable for ``Depends()``.
    """

    def _dependency(**kwargs: Any) -> T:
        # Filter out None values so they don't override defaults
        provided = {k: v for k, v in kwargs.items() if v is not None}
        return model(**provided)

    # Dynamically build the dependency signature from model fields
    import inspect

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
    """Convert a filter model to a dict suitable for repository ``filters`` param.

    Only includes fields that were explicitly set (non-None).
    """
    return {k: v for k, v in model.model_dump().items() if v is not None}

"""Reusable pagination + sort dependencies for FastAPI endpoints.

Drop-in query-param dependencies so every endpoint doesn't hand-roll
``skip`` / ``limit`` / ``sort``. Usage::

    from forge_core.api import PaginationParams, SortParams

    @router.get("/items")
    async def list_items(
        page: PaginationParams = Depends(),
        sort: SortParams = Depends(),
    ) -> PaginatedResponse[ItemOut]:
        items = await repo.get_all(skip=page.skip, limit=page.limit, sort_by=sort.fields)
        total = await repo.count()
        return page.response(items=items, total=total)

Targets Python 3.11, so generic envelopes use ``typing.Generic`` rather than
the 3.12 ``class X[T]`` syntax.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard offset/limit pagination envelope."""

    items: list[T]
    total: int
    skip: int
    limit: int
    has_more: bool


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based pagination envelope."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool


class PaginationParams:
    """FastAPI dependency extracting + validating offset/limit query params.

    Inject via ``page: PaginationParams = Depends()``.
    """

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Number of items to skip"),
        limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    ) -> None:
        self.skip = skip
        self.limit = limit

    def response(self, *, items: list[Any], total: int) -> PaginatedResponse[Any]:
        return PaginatedResponse(
            items=items,
            total=total,
            skip=self.skip,
            limit=self.limit,
            has_more=(self.skip + self.limit) < total,
        )


class CursorPaginationParams:
    """Cursor-based pagination for large or frequently-changing datasets.

    The client supplies an opaque ``cursor`` (typically the last item's id or
    timestamp) plus a ``limit``. Inject via ``Depends()``.
    """

    def __init__(
        self,
        cursor: str | None = Query(None, description="Opaque cursor from previous page"),
        limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    ) -> None:
        self.cursor = cursor
        self.limit = limit


class SortParams:
    """FastAPI dependency parsing a comma-separated sort spec.

    Prefix a field with ``-`` for descending, e.g. ``?sort=-created_at,name``.
    Inject via ``sort: SortParams = Depends()``.
    """

    def __init__(
        self,
        sort: str | None = Query(
            None,
            description=(
                "Comma-separated sort fields. Prefix - for descending. E.g. -created_at,name"
            ),
        ),
    ) -> None:
        self.fields: list[str] = []
        if sort:
            self.fields = [s.strip() for s in sort.split(",") if s.strip()]


__all__ = [
    "CursorPaginatedResponse",
    "CursorPaginationParams",
    "PaginatedResponse",
    "PaginationParams",
    "SortParams",
]

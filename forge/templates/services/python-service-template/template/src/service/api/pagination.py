"""Reusable pagination dependencies for FastAPI.

Usage in an endpoint::

    from service.api.pagination import PaginationParams, SortParams

    @router.get("/items")
    async def list_items(
        page: PaginationParams = Depends(),
        sort: SortParams = Depends(),
    ):
        items = await repo.get_all(
            skip=page.skip, limit=page.limit, sort_by=sort.fields
        )
        total = await repo.count()
        return page.response(items=items, total=total)
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard pagination envelope."""

    items: list[T]
    total: int
    skip: int
    limit: int
    has_more: bool


class PaginationParams:
    """FastAPI dependency that extracts and validates pagination query params.

    Inject via ``page: PaginationParams = Depends()``.
    """

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Number of items to skip"),
        limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    ):
        self.skip = skip
        self.limit = limit

    def response(self, *, items: list[Any], total: int) -> PaginatedResponse:
        return PaginatedResponse(
            items=items,
            total=total,
            skip=self.skip,
            limit=self.limit,
            has_more=(self.skip + self.limit) < total,
        )


class CursorPaginationParams:
    """Cursor-based pagination for large or frequently-changing datasets.

    Instead of skip/limit, the client provides an opaque ``cursor`` token
    (typically the last item's ID or timestamp) and a ``limit``.

    Inject via ``page: CursorPaginationParams = Depends()``.
    """

    def __init__(
        self,
        cursor: str | None = Query(None, description="Opaque cursor from previous page"),
        limit: int = Query(50, ge=1, le=500, description="Maximum items to return"),
    ):
        self.cursor = cursor
        self.limit = limit


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based pagination envelope."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool


class SortParams:
    """FastAPI dependency that parses sort query params.

    Accepts a comma-separated list of field names. Prefix ``-`` for descending.

    Example: ``?sort=-created_at,name``

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
    ):
        self.fields: list[str] = []
        if sort:
            self.fields = [s.strip() for s in sort.split(",") if s.strip()]

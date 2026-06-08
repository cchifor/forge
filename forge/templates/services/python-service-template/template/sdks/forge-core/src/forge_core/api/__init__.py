"""``forge_core.api`` — reusable FastAPI endpoint glue.

Generic pagination / sort / filter dependencies so endpoints don't hand-roll
``skip`` / ``limit`` / ``sort`` / per-field filter query params:

* :class:`PaginationParams`, :class:`PaginatedResponse` — offset/limit.
* :class:`CursorPaginationParams`, :class:`CursorPaginatedResponse` — cursor.
* :class:`SortParams` — ``?sort=-created_at,name``.
* :func:`filter_dependency`, :func:`to_repo_filters` — model-driven filters.
"""

from forge_core.api.filtering import filter_dependency, to_repo_filters
from forge_core.api.pagination import (
    CursorPaginatedResponse,
    CursorPaginationParams,
    PaginatedResponse,
    PaginationParams,
    SortParams,
)

__all__ = [
    "CursorPaginatedResponse",
    "CursorPaginationParams",
    "PaginatedResponse",
    "PaginationParams",
    "SortParams",
    "filter_dependency",
    "to_repo_filters",
]

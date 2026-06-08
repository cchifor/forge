"""Behaviour tests for ``forge_core.api`` pagination / sort / filter helpers."""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel

from forge_core.api import (
    CursorPaginatedResponse,
    CursorPaginationParams,
    PaginatedResponse,
    PaginationParams,
    SortParams,
    filter_dependency,
    to_repo_filters,
)


class TestPagination:
    def test_response_has_more_true(self) -> None:
        page = PaginationParams(skip=0, limit=10)
        resp = page.response(items=list(range(10)), total=25)
        assert isinstance(resp, PaginatedResponse)
        assert resp.skip == 0 and resp.limit == 10 and resp.total == 25
        assert resp.has_more is True

    def test_response_has_more_false_on_last_page(self) -> None:
        page = PaginationParams(skip=20, limit=10)
        resp = page.response(items=[1, 2, 3, 4, 5], total=25)
        assert resp.has_more is False

    def test_cursor_params_and_envelope(self) -> None:
        page = CursorPaginationParams(cursor="abc", limit=5)
        assert page.cursor == "abc" and page.limit == 5
        env = CursorPaginatedResponse(items=[1, 2], next_cursor="def", has_more=True)
        assert env.next_cursor == "def" and env.has_more is True


class TestSort:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("-created_at,name", ["-created_at", "name"]),
            (" a , , b ", ["a", "b"]),
            ("", []),
            (None, []),
        ],
    )
    def test_parse(self, raw: str | None, expected: list[str]) -> None:
        assert SortParams(sort=raw).fields == expected


class _ItemFilter(BaseModel):
    status: str | None = None
    search: str | None = None


class TestFiltering:
    def test_dependency_signature_exposes_fields(self) -> None:
        dep = filter_dependency(_ItemFilter)
        sig = inspect.signature(dep)
        assert set(sig.parameters) == {"status", "search"}

    def test_dependency_drops_none_and_builds_model(self) -> None:
        dep = filter_dependency(_ItemFilter)
        result = dep(status="open", search=None)
        assert isinstance(result, _ItemFilter)
        assert result.status == "open"
        assert result.search is None

    def test_to_repo_filters_excludes_unset(self) -> None:
        assert to_repo_filters(_ItemFilter(status="open")) == {"status": "open"}
        assert to_repo_filters(_ItemFilter()) == {}

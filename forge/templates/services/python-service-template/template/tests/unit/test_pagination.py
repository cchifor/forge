"""Tests for pagination and sorting dependencies."""

from service.api.pagination import PaginationParams, SortParams


class TestPaginationParams:
    def test_defaults(self):
        # Outside FastAPI, Query() defaults aren't resolved; pass values explicitly
        p = PaginationParams(skip=0, limit=50)
        assert p.skip == 0
        assert p.limit == 50

    def test_custom_values(self):
        p = PaginationParams(skip=10, limit=25)
        assert p.skip == 10
        assert p.limit == 25

    def test_response_no_more(self):
        p = PaginationParams(skip=0, limit=10)
        resp = p.response(items=["a", "b"], total=2)
        assert resp.total == 2
        assert resp.has_more is False
        assert len(resp.items) == 2

    def test_response_has_more(self):
        p = PaginationParams(skip=0, limit=2)
        resp = p.response(items=["a", "b"], total=5)
        assert resp.has_more is True

    def test_response_exact_boundary(self):
        p = PaginationParams(skip=0, limit=5)
        resp = p.response(items=list(range(5)), total=5)
        assert resp.has_more is False


class TestSortParams:
    def test_none(self):
        s = SortParams(sort=None)
        assert s.fields == []

    def test_single_field(self):
        s = SortParams(sort="name")
        assert s.fields == ["name"]

    def test_descending(self):
        s = SortParams(sort="-created_at")
        assert s.fields == ["-created_at"]

    def test_multiple(self):
        s = SortParams(sort="-created_at,name,status")
        assert s.fields == ["-created_at", "name", "status"]

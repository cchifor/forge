"""Tests for service.api.filtering."""

import inspect

from pydantic import BaseModel

from service.api.filtering import filter_dependency, to_repo_filters


class _SampleFilter(BaseModel):
    status: str | None = None
    search: str | None = None


class TestFilterDependency:
    def test_creates_callable(self):
        dep = filter_dependency(_SampleFilter)
        assert callable(dep)

    def test_signature_matches_model_fields(self):
        dep = filter_dependency(_SampleFilter)
        sig = inspect.signature(dep)
        assert "status" in sig.parameters
        assert "search" in sig.parameters

    def test_strips_none_values(self):
        dep = filter_dependency(_SampleFilter)
        result = dep(status=None, search="hello")
        assert result.status is None
        assert result.search == "hello"

    def test_all_values_provided(self):
        dep = filter_dependency(_SampleFilter)
        result = dep(status="active", search="test")
        assert result.status == "active"
        assert result.search == "test"


class TestToRepoFilters:
    def test_empty_model(self):
        model = _SampleFilter()
        assert to_repo_filters(model) == {}

    def test_populated_model(self):
        model = _SampleFilter(status="active", search="q")
        result = to_repo_filters(model)
        assert result == {"status": "active", "search": "q"}

    def test_mixed_model(self):
        model = _SampleFilter(status="draft")
        result = to_repo_filters(model)
        assert result == {"status": "draft"}

"""Tests for service.utils.fastapiutils."""

import pytest

from service.utils.fastapiutils import Error, filter_dict, query_list


class TestFilterDict:
    def test_none_returns_empty(self):
        assert filter_dict(None) == {}

    def test_valid_json(self):
        assert filter_dict('{"status": "active"}') == {"status": "active"}

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            filter_dict("not json")


class TestQueryList:
    def test_none_returns_empty(self):
        assert query_list(None) == []

    def test_csv_split(self):
        assert query_list("a,b,c") == ["a", "b", "c"]

    def test_single_value(self):
        assert query_list("only") == ["only"]


class TestErrorModel:
    def test_construction(self):
        err = Error(message="Not found", type="NotFoundError")
        assert err.message == "Not found"
        assert err.type == "NotFoundError"
        assert err.detail is None

    def test_with_detail(self):
        err = Error(message="Bad", type="ValidationError", detail={"field": "name"})
        assert err.detail == {"field": "name"}

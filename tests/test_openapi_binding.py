"""Tests for brownfield OpenAPI binding (Phase 5).

Two pure cores:
- ``flatten_refs`` resolves internal ``$ref`` chains so an external OpenAPI
  schema reduces to the ui-protocol subset the emitters/validators consume.
- the transform DSL (``apply_transform`` + ``coerce_value``) maps an upstream
  payload shape onto a contract operation's shape via field renames + a closed
  whitelist of scalar coercions.
"""

from __future__ import annotations

import pytest

from forge.codegen.openapi_binding import (
    apply_transform,
    coerce_value,
    flatten_refs,
)
from forge.errors import GeneratorError


class TestFlattenRefs:
    def test_inlines_internal_ref(self) -> None:
        components = {"Item": {"type": "object", "properties": {"id": {"type": "string"}}}}
        schema = {
            "type": "object",
            "properties": {"items": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}}},
        }
        out = flatten_refs(schema, components=components)
        assert out["properties"]["items"]["items"] == components["Item"]
        assert "$ref" not in str(out)

    def test_unresolvable_ref_raises(self) -> None:
        with pytest.raises(GeneratorError, match="Ghost|resolve"):
            flatten_refs({"$ref": "#/components/schemas/Ghost"}, components={})

    def test_cyclic_ref_raises(self) -> None:
        components = {"Node": {"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}}}}
        with pytest.raises(GeneratorError, match="cycl|circular"):
            flatten_refs({"$ref": "#/components/schemas/Node"}, components=components)


class TestCoercions:
    @pytest.mark.parametrize(
        ("value", "kind", "expected"),
        [
            ("5", "int", 5),
            (5, "str", "5"),
            ("1.5", "float", 1.5),
            ("true", "bool", True),
            ("false", "bool", False),
        ],
    )
    def test_whitelisted_coercions(self, value, kind, expected) -> None:
        assert coerce_value(value, kind) == expected

    def test_unknown_coercion_raises(self) -> None:
        with pytest.raises(GeneratorError, match="coerc"):
            coerce_value("x", "rot13")


class TestApplyTransform:
    def test_rename_and_coerce(self) -> None:
        upstream = {"data": [{"item_id": "a"}], "total": "5"}
        transform = {
            "items": "data",
            "count": {"from": "total", "coerce": "int"},
        }
        out = apply_transform(upstream, transform)
        assert out == {"items": [{"item_id": "a"}], "count": 5}

    def test_nested_path_rename(self) -> None:
        upstream = {"data": {"inner": {"v": 1}}}
        out = apply_transform(upstream, {"value": "data.inner.v"})
        assert out == {"value": 1}

    def test_missing_source_path_raises(self) -> None:
        with pytest.raises(GeneratorError, match="missing|not found|absent"):
            apply_transform({"a": 1}, {"x": "does.not.exist"})

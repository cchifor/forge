"""Tests for the TypeSpec compiler bridge (A3-5).

These tests cover the pure-Python logic (``extract_entities``,
``typespec_available``). Actually compiling ``.tsp`` files is an
integration test that depends on Node + @typespec/compiler; gated
behind availability detection.
"""

from __future__ import annotations

from unittest.mock import patch

from forge.domain.typespec import (
    TypespecUnavailable,
    extract_entities,
    typespec_available,
)


class TestTypespecAvailable:
    def test_false_without_npx(self) -> None:
        with patch("shutil.which", return_value=None):
            assert typespec_available() is False

    def test_true_with_npx(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/npx"):
            assert typespec_available() is True

    def test_true_with_tsp(self) -> None:
        # Either npx or tsp counts as "available".
        def which(name: str) -> str | None:
            return "/usr/local/bin/tsp" if name == "tsp" else None

        with patch("shutil.which", side_effect=which):
            assert typespec_available() is True


class TestExtractEntities:
    def test_empty_spec_yields_nothing(self) -> None:
        assert extract_entities({}) == []
        assert extract_entities({"components": {"schemas": {}}}) == []

    def test_simple_entity(self) -> None:
        spec = {
            "components": {
                "schemas": {
                    "Order": {
                        "type": "object",
                        "description": "A purchase order.",
                        "required": ["id", "name"],
                        "properties": {
                            "id": {"type": "string", "format": "uuid"},
                            "name": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 255,
                            },
                            "quantity": {"type": "integer"},
                            "description": {"type": "string"},
                            "status": {"$ref": "#/components/schemas/OrderStatus"},
                            "created_at": {
                                "type": "string",
                                "format": "date-time",
                            },
                        },
                    },
                }
            }
        }
        entities = extract_entities(spec)
        assert len(entities) == 1
        order = entities[0]
        assert order["name"] == "Order"
        assert order["plural"] == "orders"
        assert order["description"] == "A purchase order."

        names = {f["name"] for f in order["fields"]}
        assert names == {"id", "name", "quantity", "description", "status", "created_at"}

        name_field = next(f for f in order["fields"] if f["name"] == "name")
        assert name_field["type"] == "string"
        assert name_field["min_length"] == 1
        assert name_field["max_length"] == 255
        assert "optional" not in name_field

        desc_field = next(f for f in order["fields"] if f["name"] == "description")
        assert desc_field["optional"] is True

        id_field = next(f for f in order["fields"] if f["name"] == "id")
        assert id_field["type"] == "uuid"

        status_field = next(f for f in order["fields"] if f["name"] == "status")
        assert status_field["type"] == "enum"
        assert status_field["enum"] == "OrderStatus"

        ts_field = next(f for f in order["fields"] if f["name"] == "created_at")
        assert ts_field["type"] == "datetime"

    def test_pluralizes_policy_to_policies(self) -> None:
        spec = {
            "components": {
                "schemas": {
                    "Policy": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string", "format": "uuid"}},
                    }
                }
            }
        }
        [entity] = extract_entities(spec)
        assert entity["plural"] == "policies"

    def test_skips_non_object_schemas(self) -> None:
        spec = {
            "components": {
                "schemas": {
                    "OrderStatus": {"type": "string", "enum": ["new", "done"]},
                    "Order": {
                        "type": "object",
                        "required": ["id"],
                        "properties": {"id": {"type": "string", "format": "uuid"}},
                    },
                }
            }
        }
        entities = extract_entities(spec)
        assert [e["name"] for e in entities] == ["Order"]


class TestCompileTspUnavailable:
    def test_raises_typespec_unavailable(self, tmp_path) -> None:
        from forge.domain.typespec import compile_tsp

        (tmp_path / "main.tsp").write_text("model Foo {}\n")
        with patch("shutil.which", return_value=None):
            import pytest

            with pytest.raises(TypespecUnavailable):
                compile_tsp(tmp_path)

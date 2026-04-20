"""Tests for new-entity, add-backend, and preview CLI commands (I4-I6)."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from forge.cli.commands.new_entity import (
    _snake_case,
    build_entity_yaml,
    parse_field_spec,
)


class TestParseFieldSpec:
    def test_minimal_field(self) -> None:
        fields = parse_field_spec("name:string")
        assert fields == [{"name": "name", "type": "string"}]

    def test_multiple_fields(self) -> None:
        fields = parse_field_spec("name:string,qty:integer,active:boolean")
        assert [f["name"] for f in fields] == ["name", "qty", "active"]
        assert fields[1]["type"] == "integer"

    def test_optional_field(self) -> None:
        fields = parse_field_spec("description:string?")
        assert fields[0] == {"name": "description", "type": "string", "optional": True}

    def test_enum_field(self) -> None:
        fields = parse_field_spec("status:enum:OrderStatus")
        assert fields[0] == {"name": "status", "type": "enum", "enum": "OrderStatus"}

    def test_enum_missing_name_raises(self) -> None:
        from forge.errors import GeneratorError

        with pytest.raises(GeneratorError, match="enum name"):
            parse_field_spec("status:enum")


class TestBuildEntityYaml:
    def test_produces_valid_yaml_with_crud_baseline(self) -> None:
        import yaml

        body = build_entity_yaml("Order", "name:string,qty:integer")
        parsed = yaml.safe_load(body)
        field_names = [f["name"] for f in parsed["fields"]]
        assert "id" in field_names
        assert "name" in field_names
        assert "qty" in field_names
        assert "customer_id" in field_names
        assert "user_id" in field_names
        assert "created_at" in field_names
        assert "updated_at" in field_names

    def test_indices_added_when_name_field_present(self) -> None:
        import yaml

        body = build_entity_yaml("Order", "name:string")
        parsed = yaml.safe_load(body)
        assert parsed["indices"] == [["customer_id", "name"]]

    def test_pascal_to_snake_name(self) -> None:
        assert _snake_case("OrderLine") == "order_line"
        assert _snake_case("ABCFooBar") == "abcfoo_bar"
        assert _snake_case("item") == "item"

    def test_roundtrip_through_domain_loader(self, tmp_path: Path) -> None:
        from forge.domain import load_entity_yaml

        body = build_entity_yaml("Order", "name:string,qty:integer,status:enum:OrderStatus")
        path = tmp_path / "order.yaml"
        path.write_text(body, encoding="utf-8")
        spec = load_entity_yaml(path)
        assert spec.name == "Order"
        assert spec.plural == "orders"
        assert spec.field_by_name("status") is not None
        assert spec.field_by_name("status").enum == "OrderStatus"

"""Tests for the domain entity DSL (1.3 of the 1.0 roadmap, YAML-driven alpha)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.domain import EntityField, EntitySpec, FieldType, load_all, load_entity_yaml
from forge.domain.emitters import (
    emit_all,
    emit_openapi,
    emit_pydantic,
    emit_rust_struct,
    emit_zod,
)
from forge.errors import GeneratorError


SHIPPED_DOMAIN = Path(__file__).resolve().parent.parent / "forge" / "templates" / "_domain"


@pytest.fixture
def item_spec() -> EntitySpec:
    return load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")


class TestLoadEntityYaml:
    def test_loads_shipped_item(self, item_spec: EntitySpec) -> None:
        assert item_spec.name == "Item"
        assert item_spec.plural == "items"
        assert item_spec.primary_key is not None
        assert item_spec.primary_key.name == "id"

    def test_field_lookup(self, item_spec: EntitySpec) -> None:
        status = item_spec.field_by_name("status")
        assert status is not None
        assert status.type is FieldType.ENUM
        assert status.enum == "ItemStatus"

    def test_indices_captured(self, item_spec: EntitySpec) -> None:
        assert ("customer_id", "name") in item_spec.indices
        assert ("customer_id", "status") in item_spec.indices

    def test_rejects_lowercase_name(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: lowercase\nplural: x\nfields: [{name: id, type: uuid}]\n")
        with pytest.raises(GeneratorError, match="PascalCase"):
            load_entity_yaml(bad)

    def test_rejects_uppercase_plural(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: Foo\nplural: Items\nfields: [{name: id, type: uuid}]\n")
        with pytest.raises(GeneratorError, match="snake_case"):
            load_entity_yaml(bad)

    def test_rejects_unknown_field_type(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "name: Foo\nplural: foos\nfields:\n  - name: x\n    type: dinosaur\n"
        )
        with pytest.raises(GeneratorError, match="unknown type"):
            load_entity_yaml(bad)

    def test_rejects_enum_without_enum_name(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("name: Foo\nplural: foos\nfields:\n  - name: s\n    type: enum\n")
        with pytest.raises(GeneratorError, match="enum"):
            load_entity_yaml(bad)


class TestEmitPydantic:
    def test_emits_basemodel(self, item_spec: EntitySpec) -> None:
        out = emit_pydantic(item_spec)
        assert "class Item(BaseModel):" in out
        assert "from app.domain.enums import ItemStatus" in out
        assert "id: UUID" in out
        assert "created_at: datetime" in out

    def test_optional_fields_have_none_default(self, item_spec: EntitySpec) -> None:
        out = emit_pydantic(item_spec)
        assert "description: str | None = None" in out

    def test_string_length_constraints(self, item_spec: EntitySpec) -> None:
        out = emit_pydantic(item_spec)
        assert "min_length=1" in out
        assert "max_length=255" in out


class TestEmitZod:
    def test_emits_schema_and_type(self, item_spec: EntitySpec) -> None:
        out = emit_zod(item_spec)
        assert "export const ItemSchema = z.object({" in out
        assert "export type Item = z.infer<typeof ItemSchema>;" in out

    def test_uuid_becomes_string_uuid(self, item_spec: EntitySpec) -> None:
        out = emit_zod(item_spec)
        assert "z.string().uuid()" in out

    def test_optional_marks(self, item_spec: EntitySpec) -> None:
        out = emit_zod(item_spec)
        assert ".optional()" in out

    def test_array_field(self, item_spec: EntitySpec) -> None:
        out = emit_zod(item_spec)
        assert "z.array(z.string())" in out


class TestEmitRust:
    def test_emits_struct_with_derives(self, item_spec: EntitySpec) -> None:
        out = emit_rust_struct(item_spec)
        assert "pub struct Item {" in out
        assert "Serialize" in out
        assert "FromRow" in out

    def test_uuid_and_datetime_types(self, item_spec: EntitySpec) -> None:
        out = emit_rust_struct(item_spec)
        assert "pub id: Uuid," in out
        assert "pub created_at: DateTime<Utc>," in out

    def test_optional_becomes_option(self, item_spec: EntitySpec) -> None:
        out = emit_rust_struct(item_spec)
        assert "pub description: Option<String>," in out


class TestEmitOpenapi:
    def test_produces_object_schema(self, item_spec: EntitySpec) -> None:
        out = emit_openapi(item_spec)
        assert out["type"] == "object"
        assert "id" in out["properties"]
        assert out["properties"]["id"]["format"] == "uuid"

    def test_required_matches_non_optional_fields(self, item_spec: EntitySpec) -> None:
        out = emit_openapi(item_spec)
        assert "id" in out["required"]
        assert "description" not in out["required"]

    def test_enum_is_ref(self, item_spec: EntitySpec) -> None:
        out = emit_openapi(item_spec)
        assert out["properties"]["status"] == {"$ref": "#/components/schemas/ItemStatus"}


class TestEmitAll:
    def test_all_targets_produce_output(self, item_spec: EntitySpec) -> None:
        out = emit_all(item_spec)
        assert set(out) == {"pydantic", "zod", "rust", "openapi"}
        for target, body in out.items():
            assert body and "Item" in body


class TestLoadAll:
    def test_loads_shipped_domain_dir(self) -> None:
        specs = load_all(SHIPPED_DOMAIN)
        assert any(s.name == "Item" for s in specs)

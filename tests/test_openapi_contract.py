"""Contract tests — validate that forge's emitted OpenAPI is consumable
by the frontend codegens (A5-6).

These tests don't spin up the full openapi-ts / openapi-generator
toolchain (too slow for a unit-test matrix); they assert the shape
invariants those tools rely on:

  * Every entity emits an OpenAPI schema under components.schemas.<Name>
  * Every property has a `type` (or `$ref`) so openapi-ts can generate
    a typed field
  * Every schema has `required` so non-optional fields are non-nullable
  * Date / uuid formats are declared so clients produce the right
    typed representation (string with validator vs native Date)

Downstream integration tests (generated-project native test suites on
CI) exercise the full codegen path — this is the cheap-and-fast gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.codegen.ui_protocol import (
    DEFAULT_SCHEMA_ROOT as UI_PROTOCOL_ROOT,
    load_all as load_ui_schemas,
)
from forge.domain import load_entity_yaml
from forge.domain.emitters import emit_openapi


SHIPPED_DOMAIN = Path(__file__).resolve().parent.parent / "forge" / "templates" / "_domain"


class TestDomainOpenApiContract:
    def test_item_entity_has_valid_openapi(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        assert openapi["type"] == "object"
        assert "properties" in openapi
        assert "required" in openapi

    def test_every_property_has_a_type_or_ref(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        for name, prop in openapi["properties"].items():
            has_type = "type" in prop
            has_ref = "$ref" in prop
            assert has_type or has_ref, (
                f"property {name!r} has neither 'type' nor '$ref' — "
                f"openapi-ts would generate it as `any`"
            )

    def test_uuid_fields_have_format(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        id_prop = openapi["properties"]["id"]
        assert id_prop.get("type") == "string"
        assert id_prop.get("format") == "uuid"

    def test_datetime_fields_have_format(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        created_at = openapi["properties"]["created_at"]
        assert created_at.get("type") == "string"
        assert created_at.get("format") == "date-time"

    def test_enum_fields_use_ref(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        status = openapi["properties"]["status"]
        assert "$ref" in status
        assert status["$ref"].endswith("/ItemStatus")

    def test_string_length_constraints_carried_through(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        name_prop = openapi["properties"]["name"]
        assert name_prop.get("minLength") == 1
        assert name_prop.get("maxLength") == 255

    def test_optional_fields_excluded_from_required(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        # description is optional in the shipped items.yaml
        assert "description" in openapi["properties"]
        assert "description" not in openapi["required"]

    def test_required_fields_included_in_required(self) -> None:
        spec = load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")
        openapi = emit_openapi(spec)
        for name in ("id", "name", "customer_id", "user_id", "created_at", "updated_at"):
            assert name in openapi["required"], f"{name!r} should be required"


class TestUiProtocolOpenApiShape:
    """Verify the UI-protocol schemas themselves produce valid JSON Schema
    that openapi-style consumers (Pydantic, TS codegen, Dart json_serializable)
    can parse without gymnastics."""

    def test_every_shipped_schema_has_title(self) -> None:
        schemas = load_ui_schemas(UI_PROTOCOL_ROOT)
        for schema in schemas:
            assert schema.title, f"{schema.source}: missing title"

    def test_every_shipped_schema_is_object(self) -> None:
        schemas = load_ui_schemas(UI_PROTOCOL_ROOT)
        for schema in schemas:
            assert schema.body.get("type") == "object", (
                f"{schema.source}: top-level must be type=object"
            )

    def test_all_required_fields_have_properties(self) -> None:
        """A ``required`` entry that doesn't appear in ``properties``
        would crash downstream codegen. Guard here."""
        schemas = load_ui_schemas(UI_PROTOCOL_ROOT)
        for schema in schemas:
            required = set(schema.body.get("required") or ())
            props = set(schema.body.get("properties") or {})
            missing = required - props
            assert not missing, (
                f"{schema.title}: required fields missing from properties: {missing}"
            )


class TestCanvasManifestContract:
    """Verify the canvas manifest is consumable as-is by the runtime lint layer."""

    def test_every_component_has_props_schema(self) -> None:
        from forge.codegen.canvas_contract import build_manifest, load_components

        components = load_components()
        manifest = build_manifest(components)
        for name, entry in manifest["components"].items():
            assert "props_schema" in entry
            schema = entry["props_schema"]
            assert "properties" in schema, f"{name}: missing properties"

    def test_manifest_schemas_match_lint_shape(self) -> None:
        """The lint functions in packages/canvas-vue/src/lint.ts consume
        the same shape — a quick shape check here means we don't ship
        schemas that the frontend can't validate."""
        from forge.codegen.canvas_contract import build_manifest, load_components

        components = load_components()
        manifest = build_manifest(components)
        for name, entry in manifest["components"].items():
            schema = entry["props_schema"]
            # Every schema we ship declares additionalProperties (true or false).
            assert "additionalProperties" in schema, (
                f"{name}: missing additionalProperties (lint can't decide prop-drift policy)"
            )

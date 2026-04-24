"""Phase C completion — recursive OBJECT validation + JSON schema.

Covers the two Phase C follow-on items:

* ``Option.object_schema`` (``dict[str, ObjectFieldSpec]``) enables
  TypedDict-style nested-field validation for OBJECT-typed options.
  Missing required keys, unknown keys, type-mismatched values, and
  ENUM values outside the spec's allow-list all raise at
  ``validate_value`` time.

* ``to_json_schema()`` emits nested ``properties`` + ``required`` +
  ``additionalProperties=false`` for OBJECT options that declare an
  ``object_schema``. Options without a declared schema keep emitting
  bare ``{"type":"object"}`` (pre-C behaviour).

The snapshot test pins the output shape for the layer-mode options and
asserts that a synthetic OBJECT-schema option serialises correctly —
so a future edit that accidentally regresses the schema emitter fails
loudly.
"""

from __future__ import annotations

import pytest

from forge.options import (
    FeatureCategory,
    ObjectFieldSpec,
    Option,
    OptionType,
    to_json_schema,
)


# -- ObjectFieldSpec ---------------------------------------------------------


class TestObjectFieldSpec:
    def test_basic_field(self):
        spec = ObjectFieldSpec(type=OptionType.STR)
        assert spec.required is True
        assert spec.options == ()

    def test_rejects_nested_object(self):
        with pytest.raises(ValueError, match=r"OBJECT is not supported"):
            ObjectFieldSpec(type=OptionType.OBJECT)

    def test_enum_requires_options(self):
        with pytest.raises(ValueError, match=r"ENUM requires a non-empty"):
            ObjectFieldSpec(type=OptionType.ENUM)

    def test_non_enum_rejects_options(self):
        with pytest.raises(ValueError, match=r"`options` is only valid for ENUM"):
            ObjectFieldSpec(type=OptionType.STR, options=("a", "b"))


# -- Option + object_schema --------------------------------------------------


def _api_target_option(default: dict | None = None, **kwargs) -> Option:
    """Helper — a plausible OBJECT option with a typed shape.

    Mirrors the shape the plan describes for ``frontend.api_target``:
    ``{ type: "local"|"external", url: str }``. Not the real forge
    option (we ship the flat pair in B2); this one exists purely to
    exercise the schema plumbing.
    """
    return Option(
        path="test.api_target",
        type=OptionType.OBJECT,
        default=default if default is not None else {"type": "local", "url": ""},
        summary="Test OBJECT option",
        description="d",
        category=FeatureCategory.PLATFORM,
        stability="experimental",
        object_schema={
            "type": ObjectFieldSpec(
                type=OptionType.ENUM,
                options=("local", "external"),
                default="local",
            ),
            "url": ObjectFieldSpec(type=OptionType.STR, required=False, default=""),
        },
        **kwargs,
    )


class TestRecursiveObjectValidation:
    def test_valid_dict_passes(self):
        opt = _api_target_option()
        opt.validate_value({"type": "external", "url": "https://api.example.com"})

    def test_missing_required_raises(self):
        opt = _api_target_option()
        with pytest.raises(ValueError, match=r"required OBJECT key 'type' is missing"):
            opt.validate_value({"url": "https://x"})

    def test_optional_missing_is_fine(self):
        opt = _api_target_option()
        opt.validate_value({"type": "local"})  # url is optional

    def test_unknown_key_rejected(self):
        opt = _api_target_option()
        with pytest.raises(ValueError, match=r"unknown OBJECT key 'extra'"):
            opt.validate_value({"type": "local", "url": "", "extra": 1})

    def test_wrong_type_on_field(self):
        opt = _api_target_option()
        with pytest.raises(ValueError, match=r"url: expected str"):
            opt.validate_value({"type": "local", "url": 42})

    def test_enum_value_outside_options(self):
        opt = _api_target_option()
        with pytest.raises(ValueError, match=r"type: invalid value 'remote'"):
            opt.validate_value({"type": "remote", "url": "x"})

    def test_no_schema_falls_back_to_outer_check(self):
        """OBJECT options without ``object_schema`` keep pre-C behaviour
        — any dict passes, non-dict raises."""
        opt = Option(
            path="test.loose",
            type=OptionType.OBJECT,
            default={},
            summary="x",
            description="x",
            category=FeatureCategory.PLATFORM,
            stability="experimental",
        )
        opt.validate_value({"anything": "goes", "even": 42})  # no raise
        with pytest.raises(ValueError, match=r"expected dict"):
            opt.validate_value("nope")


# -- to_json_schema() emission -----------------------------------------------


class TestJsonSchemaEmission:
    def test_layer_modes_present_in_schema(self):
        schema = to_json_schema()
        props = schema["properties"]
        for path in (
            "backend.mode",
            "frontend.mode",
            "database.mode",
            "agent.mode",
        ):
            assert path in props, f"{path} missing from JSON schema"
            assert props[path]["type"] == "string"
            assert "enum" in props[path]
            assert "none" in props[path]["enum"]

    def test_schema_has_required_top_level_keys(self):
        schema = to_json_schema()
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False

    def test_object_with_schema_emits_nested_properties(self):
        """A registered OBJECT option with ``object_schema`` must emit
        a nested-schema dict, not bare ``{"type":"object"}``."""
        # Manually register + clean up so we don't leak state across tests.
        from forge.options import OPTION_REGISTRY, register_option

        opt = _api_target_option()
        register_option(opt)
        try:
            schema = to_json_schema()
            prop = schema["properties"]["test.api_target"]
            assert prop["type"] == "object"
            assert prop["additionalProperties"] is False
            assert "properties" in prop
            assert set(prop["properties"]) == {"type", "url"}
            assert prop["properties"]["type"]["type"] == "string"
            assert prop["properties"]["type"]["enum"] == ["local", "external"]
            assert prop["properties"]["url"]["type"] == "string"
            assert prop["required"] == ["type"]
        finally:
            OPTION_REGISTRY.pop("test.api_target", None)

    def test_object_without_schema_emits_bare_object(self):
        """Loose OBJECT options (no ``object_schema``) keep emitting
        a bare ``{"type":"object"}`` — preserves pre-C behaviour."""
        from forge.options import OPTION_REGISTRY, register_option

        opt = Option(
            path="test.loose_schema",
            type=OptionType.OBJECT,
            default={},
            summary="x",
            description="x",
            category=FeatureCategory.PLATFORM,
            stability="experimental",
        )
        register_option(opt)
        try:
            schema = to_json_schema()
            prop = schema["properties"]["test.loose_schema"]
            assert prop["type"] == "object"
            assert "properties" not in prop
            assert "required" not in prop
        finally:
            OPTION_REGISTRY.pop("test.loose_schema", None)


# -- Snapshot shape ---------------------------------------------------------


class TestSchemaSnapshot:
    """Pins the structural invariants of the emitted schema so a
    regression in the emitter fails a targeted test rather than trickle
    out via consumer breakage.
    """

    def test_every_registered_option_appears_exactly_once(self):
        from forge.options import OPTION_REGISTRY

        schema = to_json_schema()
        props = schema["properties"]
        for path in OPTION_REGISTRY:
            assert path in props
        # No phantom keys: schema's properties match the registry.
        assert set(props) == set(OPTION_REGISTRY)

    def test_enum_options_emit_enum_array(self):
        from forge.options import OPTION_REGISTRY

        schema = to_json_schema()
        for path, opt in OPTION_REGISTRY.items():
            if opt.type is OptionType.ENUM:
                assert "enum" in schema["properties"][path]
                assert list(schema["properties"][path]["enum"]) == list(opt.options)

    def test_int_options_emit_min_max_when_set(self):
        from forge.options import OPTION_REGISTRY

        schema = to_json_schema()
        for path, opt in OPTION_REGISTRY.items():
            if opt.type is OptionType.INT and opt.min is not None:
                assert schema["properties"][path]["minimum"] == opt.min
            if opt.type is OptionType.INT and opt.max is not None:
                assert schema["properties"][path]["maximum"] == opt.max

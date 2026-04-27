"""JSON Schema 2020-12 emitter for the option registry.

Split from ``_registry`` so the schema-emitter module can be imported
in isolation by tooling that doesn't need the registry mutation API.
"""

from __future__ import annotations

from typing import Any

from forge.options._registry import OptionType, ordered_options


def to_json_schema() -> dict[str, Any]:
    """Return the whole registry as a JSON Schema 2020-12 document.

    Each Option becomes a property on the top-level object. ``title`` /
    ``description`` / ``default`` / ``enum`` / ``minimum`` / ``maximum``
    / ``pattern`` follow the standard schema vocabulary so any
    JSON-Schema library can validate user configs without custom logic.

    ``additionalProperties`` is ``false`` — unknown option paths fail
    validation. Consumers wanting laxer behavior can edit the dumped
    document.
    """
    properties: dict[str, dict[str, Any]] = {}
    for opt in ordered_options():
        prop: dict[str, Any] = {
            "title": opt.path,
            "description": opt.summary or opt.description.splitlines()[0]
            if opt.description
            else "",
            "default": opt.default,
        }
        if opt.type is OptionType.BOOL:
            prop["type"] = "boolean"
        elif opt.type is OptionType.ENUM:
            # JSON-Schema "enum" constrains to the options set; the
            # underlying type is whatever the values are (usually string).
            prop["type"] = _python_to_schema_type(opt.options[0])
            prop["enum"] = list(opt.options)
        elif opt.type is OptionType.INT:
            prop["type"] = "integer"
            if opt.min is not None:
                prop["minimum"] = opt.min
            if opt.max is not None:
                prop["maximum"] = opt.max
        elif opt.type is OptionType.STR:
            prop["type"] = "string"
            if opt.pattern is not None:
                prop["pattern"] = opt.pattern
        elif opt.type is OptionType.LIST:
            prop["type"] = "array"
        elif opt.type is OptionType.OBJECT:
            prop["type"] = "object"
            if opt.object_schema:
                nested_props: dict[str, dict[str, Any]] = {}
                required_keys: list[str] = []
                for key, spec in opt.object_schema.items():
                    field: dict[str, Any] = {}
                    if spec.type is OptionType.BOOL:
                        field["type"] = "boolean"
                    elif spec.type is OptionType.INT:
                        field["type"] = "integer"
                    elif spec.type is OptionType.STR:
                        field["type"] = "string"
                    elif spec.type is OptionType.LIST:
                        field["type"] = "array"
                    elif spec.type is OptionType.ENUM:
                        field["type"] = _python_to_schema_type(spec.options[0])
                        field["enum"] = list(spec.options)
                    if spec.default is not None:
                        field["default"] = spec.default
                    nested_props[key] = field
                    if spec.required:
                        required_keys.append(key)
                prop["properties"] = nested_props
                prop["additionalProperties"] = False
                if required_keys:
                    prop["required"] = required_keys
        properties[opt.path] = prop

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "forge options",
        "description": "Typed configuration surface for the forge project generator.",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


def _python_to_schema_type(value: Any) -> str:
    """Map a Python value's runtime type to a JSON-Schema type literal."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"

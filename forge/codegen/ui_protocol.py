"""Generate TypeScript / Dart / Pydantic types from UI-protocol JSON schemas.

Schemas live in ``forge/templates/_shared/ui-protocol/*.schema.json``.
This module reads them and emits type definitions for the three frontend
targets (Vue, Svelte, Flutter) plus Pydantic models for backends.

Scope: a deliberately narrow JSON Schema subset that matches the protocol
shapes forge actually ships. Covers:

    * type: object, string, integer, number, boolean, array
    * string `enum` (literal union)
    * string `const` (singleton literal)
    * nested objects (rendered as inline sub-types)
    * required / optional fields
    * additionalProperties: true/false

Out of scope (report explicit error if encountered): $ref, oneOf/anyOf/allOf,
patternProperties, conditionals (if/then/else), discriminated unions.
If a shipped schema later needs those, extend here rather than hand-rolling.
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.errors import GeneratorError


def _wrap_docstring(desc: str, indent: str = "    ", line_length: int = 100) -> list[str]:
    """Render ``desc`` as a single- or multi-line Python docstring.

    Generated services run with ruff's ``E501`` rule (line-length 100) and
    schema descriptions occasionally exceed that. Wrap long descriptions
    rather than emitting one massive line.
    """
    overhead = len(indent) + 6  # indent + ``"""`` + ``"""`` = 6 chars
    if len(desc) <= line_length - overhead:
        return [f'{indent}"""{desc}"""']
    wrapped = textwrap.wrap(desc, width=line_length - len(indent))
    return [f'{indent}"""', *(f"{indent}{w}" for w in wrapped), f'{indent}"""']


# -- Schema loading -----------------------------------------------------------


@dataclass(frozen=True)
class Schema:
    """A loaded JSON schema — just the raw dict + its title for error messages."""

    title: str
    body: dict[str, Any]
    source: Path | None = None

    @property
    def description(self) -> str:
        return str(self.body.get("description") or "")


def load_schema(path: Path) -> Schema:
    """Load and minimally validate a JSON Schema file."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise GeneratorError(f"{path}: schema must be a JSON object")
    title = raw.get("title")
    if not isinstance(title, str) or not title:
        raise GeneratorError(f"{path}: `title` is required and must be a PascalCase string")
    if not re.match(r"^[A-Z][A-Za-z0-9_]*$", title):
        raise GeneratorError(f"{path}: `title` must be PascalCase (got {title!r})")
    return Schema(title=title, body=raw, source=path)


def load_all(root: Path) -> list[Schema]:
    """Load every ``*.schema.json`` under ``root``, sorted by title."""
    schemas: list[Schema] = []
    for p in sorted(root.glob("*.schema.json")):
        schemas.append(load_schema(p))
    return schemas


# -- Emitters -----------------------------------------------------------------
#
# Each emitter produces a SELF-CONTAINED file body for one target: no shared
# headers, no imports across emitters. The caller composes multiple schemas
# into one output file if that's what the target template expects.


def emit_typescript(schemas: list[Schema]) -> str:
    """Emit a TS module declaring every schema as an `export interface` / type."""
    lines: list[str] = [
        "// Generated from forge/templates/_shared/ui-protocol/*.schema.json",
        "// Do not edit by hand — regenerate via `python -m forge.codegen.ui_protocol`.",
        "",
    ]
    for schema in schemas:
        lines.append(_ts_for_schema(schema))
        lines.append("")
    return "\n".join(lines)


def _ts_for_schema(schema: Schema) -> str:
    body = schema.body
    if body.get("type") != "object":
        raise GeneratorError(f"{schema.title}: top-level schema must be type=object")
    desc = schema.description
    out: list[str] = []
    if desc:
        out.append(f"/** {desc} */")
    fields = _ts_object_body(body)
    out.append(f"export interface {schema.title} {fields}")
    return "\n".join(out)


def _ts_object_body(body: dict[str, Any]) -> str:
    props = body.get("properties") or {}
    required = set(body.get("required") or [])
    lines: list[str] = ["{"]
    for name in props:
        prop_schema = props[name]
        optional_mark = "" if name in required else "?"
        ts_type = _ts_type_for(prop_schema)
        desc = prop_schema.get("description")
        if desc:
            lines.append(f"  /** {desc} */")
        lines.append(f"  {name}{optional_mark}: {ts_type};")
    if body.get("additionalProperties") is True:
        lines.append("  [key: string]: unknown;")
    lines.append("}")
    return "\n".join(lines)


def _ts_type_for(prop: dict[str, Any]) -> str:
    if "enum" in prop:
        return " | ".join(json.dumps(v) for v in prop["enum"])
    if "const" in prop:
        return json.dumps(prop["const"])
    ty = prop.get("type")
    if ty == "string":
        return "string"
    if ty == "integer" or ty == "number":
        return "number"
    if ty == "boolean":
        return "boolean"
    if ty == "array":
        items = prop.get("items") or {"type": "string"}
        return f"Array<{_ts_type_for(items)}>"
    if ty == "object":
        props = prop.get("properties")
        if props:
            # Inline anonymous type
            return _ts_object_body(prop)
        if prop.get("additionalProperties") is True:
            return "Record<string, unknown>"
        return "Record<string, never>"
    if ty is None:
        return "unknown"
    raise GeneratorError(f"Unsupported JSON Schema type: {ty!r}")


# -- Dart ---------------------------------------------------------------------


def emit_dart(schemas: list[Schema]) -> str:
    """Emit a single Dart file with classes for every schema.

    Uses `Map<String, dynamic>` for `additionalProperties: true` objects;
    each generated class has a ``fromJson`` / ``toJson`` pair that pass
    through unknown keys verbatim.
    """
    lines: list[str] = [
        "// Generated from forge/templates/_shared/ui-protocol/*.schema.json",
        "// Do not edit by hand — regenerate via `python -m forge.codegen.ui_protocol`.",
        "",
    ]
    for schema in schemas:
        lines.append(_dart_for_schema(schema))
        lines.append("")
    return "\n".join(lines)


def _dart_for_schema(schema: Schema) -> str:
    body = schema.body
    if body.get("type") != "object":
        raise GeneratorError(f"{schema.title}: top-level schema must be type=object")
    title = schema.title
    props = body.get("properties") or {}
    required = set(body.get("required") or [])

    field_decls: list[str] = []
    from_json_parts: list[str] = []
    to_json_parts: list[str] = []
    ctor_params: list[str] = []

    for name in props:
        prop_schema = props[name]
        dart_type = _dart_type_for(prop_schema, name)
        is_required = name in required
        nullable_mark = "" if is_required else "?"

        # Dart field name: camelCase; JSON key stays snake_case.
        field_name = _to_camel_case(name)

        field_decls.append(f"  final {dart_type}{nullable_mark} {field_name};")
        ctor_params.append(f"    {'required ' if is_required else ''}this.{field_name},")

        from_json_parts.append(
            f"      {field_name}: {_dart_from_json(prop_schema, name, is_required)},"
        )
        to_json_parts.append(
            f"      '{name}': {_dart_to_json(prop_schema, field_name, is_required)},"
        )

    # additionalProperties handling — store extras in a map.
    if body.get("additionalProperties") is True:
        field_decls.append("  final Map<String, dynamic> extras;")
        ctor_params.append("    this.extras = const {},")

    lines: list[str] = []
    if schema.description:
        lines.append(f"/// {schema.description}")
    lines.append(f"class {title} {{")
    lines.extend(field_decls)
    lines.append("")
    lines.append(f"  const {title}({{")
    lines.extend(ctor_params)
    lines.append("  });")
    lines.append("")
    lines.append(f"  factory {title}.fromJson(Map<String, dynamic> json) => {title}(")
    lines.extend(from_json_parts)
    lines.append("  );")
    lines.append("")
    lines.append("  Map<String, dynamic> toJson() => {")
    lines.extend(to_json_parts)
    lines.append("  };")
    lines.append("}")
    return "\n".join(lines)


def _dart_type_for(prop: dict[str, Any], field_name: str) -> str:
    if "enum" in prop:
        return "String"
    if "const" in prop:
        return "String"
    ty = prop.get("type")
    if ty == "string":
        return "String"
    if ty == "integer":
        return "int"
    if ty == "number":
        return "double"
    if ty == "boolean":
        return "bool"
    if ty == "array":
        items = prop.get("items") or {"type": "string"}
        inner = _dart_type_for(items, field_name)
        return f"List<{inner}>"
    if ty == "object":
        return "Map<String, dynamic>"
    if ty is None:
        return "dynamic"
    raise GeneratorError(f"Unsupported JSON Schema type: {ty!r}")


def _dart_from_json(prop: dict[str, Any], json_key: str, required: bool) -> str:
    """Dart expression that pulls the value for ``json_key`` out of ``json``."""
    raw = f"json['{json_key}']"
    if "enum" in prop or "const" in prop:
        cast = f"{raw} as String"
    else:
        ty = prop.get("type")
        if ty == "string":
            cast = f"{raw} as String"
        elif ty == "integer":
            cast = f"{raw} as int"
        elif ty == "number":
            cast = f"({raw} as num).toDouble()"
        elif ty == "boolean":
            cast = f"{raw} as bool"
        elif ty == "array":
            items = prop.get("items") or {"type": "string"}
            inner = _dart_type_for(items, json_key)
            if inner == "Map<String, dynamic>":
                cast = f"({raw} as List).cast<Map<String, dynamic>>()"
            else:
                cast = f"({raw} as List).cast<{inner}>()"
        elif ty == "object":
            cast = f"Map<String, dynamic>.from({raw} as Map)"
        else:
            cast = raw
    if required:
        return cast
    return f"{raw} == null ? null : ({cast})"


def _dart_to_json(prop: dict[str, Any], field_name: str, required: bool) -> str:
    """Dart expression that serializes the field for inclusion in a JSON map."""
    return f"{field_name}"


# -- Pydantic -----------------------------------------------------------------


def emit_pydantic(schemas: list[Schema]) -> str:
    """Emit Pydantic v2 models for the schemas."""
    lines: list[str] = [
        '"""Generated from forge/templates/_shared/ui-protocol/*.schema.json.',
        "",
        "Regenerate via ``python -m forge.codegen.ui_protocol``.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any, Literal",
        "",
        "from pydantic import BaseModel, ConfigDict, Field",
        "",
    ]
    for schema in schemas:
        lines.append(_pydantic_for_schema(schema))
        lines.append("")
    return "\n".join(lines)


def _pydantic_for_schema(schema: Schema) -> str:
    body = schema.body
    if body.get("type") != "object":
        raise GeneratorError(f"{schema.title}: top-level schema must be type=object")
    title = schema.title
    props = body.get("properties") or {}
    required = set(body.get("required") or [])

    lines: list[str] = [f"class {title}(BaseModel):"]
    if schema.description:
        lines.extend(_wrap_docstring(schema.description))
        lines.append("")

    # Model-wide config
    if body.get("additionalProperties") is True:
        lines.append('    model_config = ConfigDict(extra="allow")')
        lines.append("")

    if not props:
        lines.append("    pass")
        return "\n".join(lines)

    for name in props:
        prop_schema = props[name]
        py_type = _pydantic_type_for(prop_schema)
        if name in required:
            lines.append(f"    {name}: {py_type}")
        else:
            lines.append(f"    {name}: {py_type} | None = None")
    return "\n".join(lines)


def _pydantic_type_for(prop: dict[str, Any]) -> str:
    if "enum" in prop:
        values = ", ".join(json.dumps(v) for v in prop["enum"])
        return f"Literal[{values}]"
    if "const" in prop:
        return f"Literal[{json.dumps(prop['const'])}]"
    ty = prop.get("type")
    if ty == "string":
        return "str"
    if ty == "integer":
        return "int"
    if ty == "number":
        return "float"
    if ty == "boolean":
        return "bool"
    if ty == "array":
        items = prop.get("items") or {"type": "string"}
        return f"list[{_pydantic_type_for(items)}]"
    if ty == "object":
        return "dict[str, Any]"
    if ty is None:
        return "Any"
    raise GeneratorError(f"Unsupported JSON Schema type: {ty!r}")


# -- helpers -----------------------------------------------------------------


def _to_camel_case(snake: str) -> str:
    parts = snake.split("_")
    if not parts:
        return snake
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


DEFAULT_SCHEMA_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "_shared" / "ui-protocol"
)


def emit_all_for_default_root() -> dict[str, str]:
    """Load every shipped schema and emit TS / Dart / Pydantic in one go."""
    schemas = load_all(DEFAULT_SCHEMA_ROOT)
    return {
        "typescript": emit_typescript(schemas),
        "dart": emit_dart(schemas),
        "pydantic": emit_pydantic(schemas),
    }

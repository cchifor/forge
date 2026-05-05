"""Per-language emitters for ``EntitySpec`` — Python / Node (Zod) / Rust / OpenAPI.

Each emitter produces a self-contained source string for one entity and
one target. Callers write the output to disk.

Covers enough of the common CRUD shape (UUID PKs, tenant scoping via
relation fields, timestamps, nullable fields, enum fields, indices) that
forge-generated projects can switch from hand-written models to generated
models without functional change. Edge cases (generics, polymorphic
relations, recursive types) are out of scope for 1.0.0a1 and documented
as TypeSpec-required for 1.0.0a2.
"""

from __future__ import annotations

from forge.domain.spec import EntityField, EntitySpec, FieldType
from forge.errors import GeneratorError

# -- Python / Pydantic --------------------------------------------------------


def emit_pydantic(spec: EntitySpec) -> str:
    """Emit a Pydantic v2 BaseModel for the entity.

    Enum fields reference Python enums by name — the caller is
    responsible for making sure the enum is importable in the target
    file (typically from the shared enums module).
    """
    lines: list[str] = [
        f'"""Generated Pydantic model for {spec.name}. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "from datetime import date, datetime",
        "from typing import Any",
        "from uuid import UUID",
        "",
        "from pydantic import BaseModel, Field",
        "",
    ]
    _add_enum_imports_python(lines, spec)
    lines.append("")
    if spec.description:
        lines.append(f"class {spec.name}(BaseModel):")
        lines.append(f'    """{spec.description}"""')
    else:
        lines.append(f"class {spec.name}(BaseModel):")
    for f in spec.fields:
        lines.append(_pydantic_field(f))
    return "\n".join(lines) + "\n"


def _add_enum_imports_python(lines: list[str], spec: EntitySpec) -> None:
    enums = sorted({f.enum for f in spec.fields if f.enum})
    for enum_name in enums:
        lines.append(f"from app.domain.enums import {enum_name}")


def _pydantic_field(f: EntityField) -> str:
    py_type = _pydantic_type(f)
    suffix = " | None" if f.optional else ""
    constraints = _pydantic_constraints(f)
    if f.optional and not constraints:
        default = " = None"
    elif constraints:
        args = constraints.copy()
        if f.optional:
            args.insert(0, "None")
        default = f" = Field({', '.join(args)})"
    else:
        default = ""
    return f"    {f.name}: {py_type}{suffix}{default}"


def _pydantic_type(f: EntityField) -> str:
    if f.type is FieldType.STRING:
        return "str"
    if f.type is FieldType.INTEGER:
        return "int"
    if f.type is FieldType.NUMBER:
        return "float"
    if f.type is FieldType.BOOLEAN:
        return "bool"
    if f.type is FieldType.UUID:
        return "UUID"
    if f.type is FieldType.DATETIME:
        return "datetime"
    if f.type is FieldType.DATE:
        return "date"
    if f.type is FieldType.JSON:
        return "dict[str, Any]"
    if f.type is FieldType.ENUM:
        return f.enum or "str"
    if f.type is FieldType.ARRAY:
        if f.of is None:
            return "list[Any]"
        return f"list[{_pydantic_type_from_str(f.of)}]"
    if f.type is FieldType.RELATION:
        return "UUID"
    raise GeneratorError(f"Unknown field type: {f.type}")


def _pydantic_type_from_str(type_name: str) -> str:
    mapping = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "uuid": "UUID",
        "datetime": "datetime",
    }
    return mapping.get(type_name, "Any")


def _pydantic_constraints(f: EntityField) -> list[str]:
    out: list[str] = []
    if f.min_length is not None:
        out.append(f"min_length={f.min_length}")
    if f.max_length is not None:
        out.append(f"max_length={f.max_length}")
    return out


# -- Zod (Node) ---------------------------------------------------------------


def emit_zod(spec: EntitySpec) -> str:
    """Emit a Zod schema + TS type for the entity."""
    lines: list[str] = [
        f"// Generated Zod schema for {spec.name}. Do not edit by hand.",
        "",
        "import { z } from 'zod';",
    ]
    for enum_name in sorted({f.enum for f in spec.fields if f.enum}):
        lines.append(f"import {{ {enum_name}Schema }} from '../schemas/enums';")
    lines.append("")
    lines.append(f"export const {spec.name}Schema = z.object({{")
    for f in spec.fields:
        lines.append(f"  {f.name}: {_zod_field(f)},")
    lines.append("});")
    lines.append("")
    lines.append(f"export type {spec.name} = z.infer<typeof {spec.name}Schema>;")
    return "\n".join(lines) + "\n"


def _zod_field(f: EntityField) -> str:
    base = _zod_type(f)
    if f.optional:
        base = f"{base}.optional()"
    return base


def _zod_type(f: EntityField) -> str:
    if f.type is FieldType.STRING:
        s = "z.string()"
        if f.min_length is not None:
            s += f".min({f.min_length})"
        if f.max_length is not None:
            s += f".max({f.max_length})"
        return s
    if f.type is FieldType.INTEGER:
        return "z.number().int()"
    if f.type is FieldType.NUMBER:
        return "z.number()"
    if f.type is FieldType.BOOLEAN:
        return "z.boolean()"
    if f.type is FieldType.UUID:
        return "z.string().uuid()"
    if f.type is FieldType.DATETIME:
        return "z.coerce.date()"
    if f.type is FieldType.DATE:
        return "z.coerce.date()"
    if f.type is FieldType.JSON:
        return "z.record(z.string(), z.unknown())"
    if f.type is FieldType.ENUM:
        return f"{f.enum}Schema" if f.enum else "z.string()"
    if f.type is FieldType.ARRAY:
        return f"z.array({_zod_inner(f.of or 'string')})"
    if f.type is FieldType.RELATION:
        return "z.string().uuid()"
    raise GeneratorError(f"Unknown field type: {f.type}")


def _zod_inner(type_name: str) -> str:
    mapping = {
        "string": "z.string()",
        "integer": "z.number().int()",
        "number": "z.number()",
        "boolean": "z.boolean()",
        "uuid": "z.string().uuid()",
        "datetime": "z.coerce.date()",
    }
    return mapping.get(type_name, "z.unknown()")


# -- Rust / sqlx -------------------------------------------------------------


def emit_rust_struct(spec: EntitySpec) -> str:
    """Emit a Rust struct with serde + sqlx::FromRow derives."""
    lines: list[str] = [
        f"// Generated Rust struct for {spec.name}. Do not edit by hand.",
        "",
        "use chrono::{DateTime, NaiveDate, Utc};",
        "use serde::{Deserialize, Serialize};",
        "use sqlx::FromRow;",
        "use uuid::Uuid;",
        "",
    ]
    for enum_name in sorted({f.enum for f in spec.fields if f.enum}):
        lines.append(f"use crate::models::enums::{enum_name};")
    lines.append("")
    lines.append("#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]")
    lines.append(f"pub struct {spec.name} {{")
    for f in spec.fields:
        rust_type = _rust_type(f)
        if f.optional:
            rust_type = f"Option<{rust_type}>"
        lines.append(f"    pub {f.name}: {rust_type},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _rust_type(f: EntityField) -> str:
    if f.type is FieldType.STRING:
        return "String"
    if f.type is FieldType.INTEGER:
        return "i64"
    if f.type is FieldType.NUMBER:
        return "f64"
    if f.type is FieldType.BOOLEAN:
        return "bool"
    if f.type is FieldType.UUID:
        return "Uuid"
    if f.type is FieldType.DATETIME:
        return "DateTime<Utc>"
    if f.type is FieldType.DATE:
        return "NaiveDate"
    if f.type is FieldType.JSON:
        return "serde_json::Value"
    if f.type is FieldType.ENUM:
        return f.enum or "String"
    if f.type is FieldType.ARRAY:
        inner = _rust_inner(f.of or "string")
        return f"Vec<{inner}>"
    if f.type is FieldType.RELATION:
        return "Uuid"
    raise GeneratorError(f"Unknown field type: {f.type}")


def _rust_inner(type_name: str) -> str:
    mapping = {
        "string": "String",
        "integer": "i64",
        "number": "f64",
        "boolean": "bool",
        "uuid": "Uuid",
        "datetime": "DateTime<Utc>",
    }
    return mapping.get(type_name, "serde_json::Value")


# -- OpenAPI ------------------------------------------------------------------


def emit_openapi(spec: EntitySpec) -> dict:
    """Emit an OpenAPI component schema for the entity.

    Returns a dict suitable for embedding under ``components.schemas.<Name>``
    of a larger OpenAPI document. Callers compose multiple entities into one.
    """
    properties: dict = {}
    required: list[str] = []
    for f in spec.fields:
        if not f.optional:
            required.append(f.name)
        properties[f.name] = _openapi_type(f)
    out: dict = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    if spec.description:
        out["description"] = spec.description
    return out


def _openapi_type(f: EntityField) -> dict:
    if f.type is FieldType.STRING:
        schema: dict = {"type": "string"}
        if f.min_length is not None:
            schema["minLength"] = f.min_length
        if f.max_length is not None:
            schema["maxLength"] = f.max_length
        return schema
    if f.type is FieldType.INTEGER:
        return {"type": "integer"}
    if f.type is FieldType.NUMBER:
        return {"type": "number"}
    if f.type is FieldType.BOOLEAN:
        return {"type": "boolean"}
    if f.type is FieldType.UUID:
        return {"type": "string", "format": "uuid"}
    if f.type is FieldType.DATETIME:
        return {"type": "string", "format": "date-time"}
    if f.type is FieldType.DATE:
        return {"type": "string", "format": "date"}
    if f.type is FieldType.JSON:
        return {"type": "object", "additionalProperties": True}
    if f.type is FieldType.ENUM:
        return {"$ref": f"#/components/schemas/{f.enum}"}
    if f.type is FieldType.ARRAY:
        inner = _openapi_inner(f.of or "string")
        return {"type": "array", "items": inner}
    if f.type is FieldType.RELATION:
        return {"type": "string", "format": "uuid"}
    raise GeneratorError(f"Unknown field type: {f.type}")


def _openapi_inner(type_name: str) -> dict:
    mapping = {
        "string": {"type": "string"},
        "integer": {"type": "integer"},
        "number": {"type": "number"},
        "boolean": {"type": "boolean"},
        "uuid": {"type": "string", "format": "uuid"},
        "datetime": {"type": "string", "format": "date-time"},
    }
    return mapping.get(type_name, {"type": "string"})


# -- Convenience --------------------------------------------------------------


def emit_all(spec: EntitySpec) -> dict[str, str]:
    """Every supported target for one entity."""
    import json

    return {
        "pydantic": emit_pydantic(spec),
        "zod": emit_zod(spec),
        "rust": emit_rust_struct(spec),
        "openapi": json.dumps(emit_openapi(spec), indent=2),
    }

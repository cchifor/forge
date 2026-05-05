"""YAML-driven entity spec — the source of truth for CRUD domain types.

Schema (``domain/<entity>.yaml``):

    name: Item
    plural: items
    description: A catalog item.
    fields:
      - name: id
        type: uuid
        primary_key: true
      - name: name
        type: string
        min_length: 1
        max_length: 255
      - name: description
        type: string
        optional: true
      - name: status
        type: enum
        enum: ItemStatus
        default: DRAFT
      - name: tags
        type: array
        of: string
      - name: customer_id
        type: uuid
      - name: user_id
        type: uuid
      - name: created_at
        type: datetime
      - name: updated_at
        type: datetime
    indices:
      - [customer_id, name]
      - [customer_id, status]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from forge.errors import GeneratorError


class FieldType(str, Enum):  # noqa: UP042  # str + Enum kept for YAML-loader compat; StrEnum changes eq semantics
    """Supported scalar/composite field types."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    UUID = "uuid"
    DATETIME = "datetime"
    DATE = "date"
    JSON = "json"
    ENUM = "enum"
    ARRAY = "array"
    RELATION = "relation"  # foreign-key reference to another entity


@dataclass(frozen=True)
class EntityField:
    """One field on an entity.

    ``optional=True`` makes the field nullable in the DB and optional in
    the API. ``primary_key=True`` designates the PK (typically ``id``).
    ``enum`` names an enum from the shared enum registry. ``of`` is the
    element type for ``array`` fields. ``target`` names the related
    entity for ``relation`` fields.
    """

    name: str
    type: FieldType
    optional: bool = False
    primary_key: bool = False
    enum: str | None = None
    of: str | None = None
    target: str | None = None
    default: Any = None
    min_length: int | None = None
    max_length: int | None = None


@dataclass(frozen=True)
class EntitySpec:
    """A domain entity — name, plural form, fields, indices."""

    name: str
    plural: str
    description: str
    fields: tuple[EntityField, ...]
    indices: tuple[tuple[str, ...], ...] = ()

    def field_by_name(self, name: str) -> EntityField | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def primary_key(self) -> EntityField | None:
        for f in self.fields:
            if f.primary_key:
                return f
        return None


def load_entity_yaml(path: Path) -> EntitySpec:
    """Load and validate an entity YAML file."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise GeneratorError(f"{path}: entity YAML must be a mapping at the top level")

    name = raw.get("name")
    if not isinstance(name, str) or not re.match(r"^[A-Z][A-Za-z0-9_]*$", name):
        raise GeneratorError(f"{path}: `name` must be a PascalCase identifier")

    plural = raw.get("plural")
    if not isinstance(plural, str) or not re.match(r"^[a-z][a-z0-9_]*$", plural):
        raise GeneratorError(f"{path}: `plural` must be a snake_case identifier (got {plural!r})")

    description = str(raw.get("description") or "")

    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, list) or not fields_raw:
        raise GeneratorError(f"{path}: `fields` must be a non-empty list")
    fields = tuple(_load_field(path, entry) for entry in fields_raw)

    indices_raw = raw.get("indices") or ()
    if not isinstance(indices_raw, list):
        raise GeneratorError(f"{path}: `indices` must be a list of lists")
    indices: list[tuple[str, ...]] = []
    for idx in indices_raw:
        if not isinstance(idx, list) or not all(isinstance(c, str) for c in idx):
            raise GeneratorError(f"{path}: each index entry must be a list of field names")
        indices.append(tuple(idx))

    return EntitySpec(
        name=name,
        plural=plural,
        description=description,
        fields=fields,
        indices=tuple(indices),
    )


def _load_field(path: Path, entry: Any) -> EntityField:
    if not isinstance(entry, dict):
        raise GeneratorError(f"{path}: field entry must be a mapping")
    name = entry.get("name")
    if not isinstance(name, str) or not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise GeneratorError(f"{path}: field `name` must be snake_case (got {name!r})")

    type_str = entry.get("type")
    try:
        ftype = FieldType(type_str)
    except ValueError:
        raise GeneratorError(
            f"{path}: field {name!r} has unknown type {type_str!r}. "
            f"Supported: {', '.join(t.value for t in FieldType)}"
        ) from None

    # Type-specific validation.
    if ftype is FieldType.ENUM and not entry.get("enum"):
        raise GeneratorError(f"{path}: field {name!r} is type=enum but missing `enum: <Name>`")
    if ftype is FieldType.ARRAY and not entry.get("of"):
        raise GeneratorError(f"{path}: field {name!r} is type=array but missing `of: <type>`")
    if ftype is FieldType.RELATION and not entry.get("target"):
        raise GeneratorError(
            f"{path}: field {name!r} is type=relation but missing `target: <Entity>`"
        )

    return EntityField(
        name=name,
        type=ftype,
        optional=bool(entry.get("optional", False)),
        primary_key=bool(entry.get("primary_key", False)),
        enum=entry.get("enum"),
        of=entry.get("of"),
        target=entry.get("target"),
        default=entry.get("default"),
        min_length=entry.get("min_length"),
        max_length=entry.get("max_length"),
    )


def load_all(root: Path) -> list[EntitySpec]:
    """Load every ``*.yaml`` under ``root`` (non-recursive), sorted by name."""
    if not root.is_dir():
        return []
    specs: list[EntitySpec] = []
    for p in sorted(root.glob("*.yaml")):
        specs.append(load_entity_yaml(p))
    return specs

"""Domain-schema subsystem — entities, fields, emitters.

Phase 1.3 of the 1.0 roadmap splits into two phases:

    1.3a (this alpha)  — YAML-driven entity specs, hand-written emitters.
                         Covers the common case (CRUD entities with typed
                         fields, enums, relations) without requiring the
                         TypeSpec toolchain.

    1.3b (follow-up)   — TypeSpec as the canonical source, per-language
                         emitters wrapping the TypeSpec compiler. The YAML
                         loader stays as a fallback for users who don't
                         want Node in their toolchain.

For 1.0.0a1 we ship the YAML loader and basic emitters. Users with existing
hand-written entity files don't need to migrate; the generator treats
``domain/*.yaml`` as optional — if present, entities are emitted from the
YAML; otherwise the legacy hand-written files remain authoritative.
"""

from forge.domain.spec import (
    EntityField,
    EntitySpec,
    FieldType,
    load_all,
    load_entity_yaml,
)

__all__ = [
    "EntityField",
    "EntitySpec",
    "FieldType",
    "load_all",
    "load_entity_yaml",
]

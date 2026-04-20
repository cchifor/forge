"""Canvas component contract — per-component props schemas + manifest.

Every canvas-renderable component has a colocated ``*.props.schema.json``.
This module loads them, emits a ``canvas.manifest.json`` (for backend
validation), and provides a ``lint`` function that checks a proposed
payload against the manifest.

Phase 1.2 of the 1.0 roadmap.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.errors import GeneratorError


@dataclass(frozen=True)
class CanvasComponentSpec:
    """One canvas component and the JSON Schema for its props."""

    name: str
    props_schema: dict[str, Any]
    description: str = ""


DEFAULT_SCHEMA_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "_shared" / "canvas-components"
)


def load_components(root: Path | None = None) -> list[CanvasComponentSpec]:
    """Load every ``*.props.schema.json`` under ``root``.

    The canvas component name is derived from the schema's ``title``
    (stripping the ``Props`` suffix): ``DataTableProps`` → ``DataTable``.
    """
    root = root or DEFAULT_SCHEMA_ROOT
    components: list[CanvasComponentSpec] = []
    for path in sorted(root.glob("*.props.schema.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        title = raw.get("title") or ""
        if not title.endswith("Props"):
            raise GeneratorError(
                f"{path}: canvas props schema title must end with 'Props' (got {title!r})"
            )
        name = title[: -len("Props")]
        components.append(
            CanvasComponentSpec(
                name=name,
                props_schema=raw,
                description=str(raw.get("description") or ""),
            )
        )
    return components


def build_manifest(components: list[CanvasComponentSpec]) -> dict[str, Any]:
    """Produce ``canvas.manifest.json`` — one entry per component."""
    return {
        "$schema": "https://forge.dev/schemas/canvas-manifest-v1.json",
        "version": 1,
        "components": {
            c.name: {
                "description": c.description,
                "props_schema": c.props_schema,
            }
            for c in components
        },
    }


def emit_manifest_json(components: list[CanvasComponentSpec] | None = None) -> str:
    """Serialize the manifest to a JSON string."""
    if components is None:
        components = load_components()
    return json.dumps(build_manifest(components), indent=2) + "\n"


# -- Validation ---------------------------------------------------------------


@dataclass(frozen=True)
class LintIssue:
    """One violation found during a canvas payload lint check."""

    component: str
    field: str
    message: str

    def __str__(self) -> str:
        where = f"{self.component}.{self.field}" if self.field else self.component
        return f"{where}: {self.message}"


def lint_payload(
    payload: dict[str, Any], components: list[CanvasComponentSpec] | None = None
) -> list[LintIssue]:
    """Check a canvas payload (``{component_name, props}``) against the manifest.

    Does a shallow props-shape check:
      * component must be registered
      * required props present
      * extra props absent when ``additionalProperties=false``
      * prop types match (string/number/integer/boolean/array/object)

    Returns a list of ``LintIssue`` — empty means clean.
    """
    if components is None:
        components = load_components()
    index = {c.name: c for c in components}

    issues: list[LintIssue] = []
    name = payload.get("component_name")
    if not isinstance(name, str):
        issues.append(LintIssue("<unknown>", "component_name", "missing or non-string"))
        return issues

    spec = index.get(name)
    if spec is None:
        issues.append(
            LintIssue(
                name,
                "",
                f"not a registered canvas component (known: {', '.join(sorted(index))})",
            )
        )
        return issues

    props = payload.get("props")
    if not isinstance(props, dict):
        issues.append(LintIssue(name, "props", "missing or non-object"))
        return issues

    schema = spec.props_schema
    declared_props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    additional_ok = schema.get("additionalProperties") is True

    for field_name in required:
        if field_name not in props:
            issues.append(LintIssue(name, field_name, "required prop is missing"))

    for field_name, value in props.items():
        if field_name not in declared_props:
            if not additional_ok:
                issues.append(LintIssue(name, field_name, "unknown prop"))
            continue
        prop_schema = declared_props[field_name]
        type_issue = _check_type(value, prop_schema)
        if type_issue:
            issues.append(LintIssue(name, field_name, type_issue))

    return issues


def _check_type(value: Any, prop_schema: dict[str, Any]) -> str | None:
    """Return an error message if ``value`` doesn't match the schema's type."""
    if "enum" in prop_schema:
        allowed = prop_schema["enum"]
        if value not in allowed:
            return f"not in enum {allowed!r}"
        return None
    ty = prop_schema.get("type")
    if ty == "string":
        return None if isinstance(value, str) else f"expected string, got {type(value).__name__}"
    if ty == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"expected integer, got {type(value).__name__}"
        return None
    if ty == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"expected number, got {type(value).__name__}"
        return None
    if ty == "boolean":
        return None if isinstance(value, bool) else f"expected boolean, got {type(value).__name__}"
    if ty == "array":
        return None if isinstance(value, list) else f"expected array, got {type(value).__name__}"
    if ty == "object":
        return None if isinstance(value, dict) else f"expected object, got {type(value).__name__}"
    return None


# -- CLI subcommand -----------------------------------------------------------


def cli_lint(payload_path: Path) -> int:
    """Load a payload from a JSON file and lint it. Returns an exit code.

    Used by ``forge canvas lint <file.json>`` (wired in Phase 2).
    """
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"error: failed to parse {payload_path}: {e}")
        return 2

    issues = lint_payload(payload)
    if not issues:
        print(f"OK: {payload.get('component_name', '?')} props match the manifest")
        return 0
    print(f"{len(issues)} lint issue(s):")
    for issue in issues:
        print(f"  * {issue}")
    return 1

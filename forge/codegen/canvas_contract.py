"""Canvas component contract — per-component props schemas + manifest.

Every canvas-renderable component has a colocated ``*.props.schema.json``.
This module loads them, emits a ``canvas.manifest.json`` (for backend
validation), and provides a ``lint`` function that checks a proposed
payload against the manifest.

Phase 1.2 of the 1.0 roadmap.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.codegen._schema_cache import load_json_schema
from forge.codegen.ui_protocol import Schema, assert_supported_schema, emit_typescript
from forge.errors import GeneratorError

# Operation kinds a data contract may declare. ``read`` fetches, ``write``
# mutates, ``subscribe`` opens a stream (e.g. the agent WS).
_VALID_OPERATION_KINDS: frozenset[str] = frozenset({"read", "write", "subscribe"})


@dataclass(frozen=True)
class ContractOperation:
    """One named operation in a component's data contract.

    ``input`` / ``output`` are JSON-Schema objects in the ui-protocol subset
    (validated via :func:`forge.codegen.ui_protocol.assert_supported_schema`).
    """

    name: str
    kind: str  # read | write | subscribe
    input: dict[str, Any]
    output: dict[str, Any]


@dataclass(frozen=True)
class DataContract:
    """A component's data-dependency set: a named set of operations.

    An empty ``operations`` tuple is a legal, representable state — it means a
    pure-UI component with no data dependency.
    """

    component: str
    operations: tuple[ContractOperation, ...] = ()


@dataclass(frozen=True)
class CanvasComponentSpec:
    """One canvas component: its props (UI surface) + optional data contract."""

    name: str
    props_schema: dict[str, Any]
    description: str = ""
    # The data-dependency set. ``None`` ⇒ pure-UI component (no contract file).
    contract: DataContract | None = None


DEFAULT_SCHEMA_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "_shared" / "canvas-components"
)


def data_contract_from_dict(data: dict[str, Any]) -> DataContract:
    """Build a :class:`DataContract` from a parsed ``*.contract.json`` dict.

    Structural parse only (shape + types); semantic validation — operation
    kinds and schema-subset compliance — is :func:`validate_data_contract`.
    """
    if not isinstance(data, dict):
        raise GeneratorError(f"data contract must be an object, got {type(data).__name__}")
    component = str(data.get("component") or "")
    ops_raw = data.get("operations", [])
    if not isinstance(ops_raw, list):
        raise GeneratorError(f"{component or '<contract>'}: operations must be a list")
    ops: list[ContractOperation] = []
    for entry in ops_raw:
        if not isinstance(entry, dict):
            raise GeneratorError(f"{component}: each operation must be an object")
        name = str(entry.get("name") or "")
        op_input = entry.get("input", {})
        op_output = entry.get("output", {})
        for field, value in (("input", op_input), ("output", op_output)):
            if not isinstance(value, dict):
                raise GeneratorError(
                    f"{component}.{name or '<unnamed>'}: operation {field} must be "
                    f"a schema object, got {type(value).__name__}"
                )
        ops.append(
            ContractOperation(
                name=name,
                kind=str(entry.get("kind") or ""),
                input=dict(op_input),
                output=dict(op_output),
            )
        )
    return DataContract(component=component, operations=tuple(ops))


def load_data_contract(path: Path) -> DataContract:
    """Load and structurally parse a ``<Component>.contract.json`` file."""
    raw = load_json_schema(path)
    return data_contract_from_dict(raw)


def validate_data_contract(contract: DataContract) -> None:
    """Raise ``GeneratorError`` if any operation is malformed or out-of-subset.

    Checks: each operation has a name, a ``kind`` in {read, write, subscribe},
    and ``input``/``output`` schemas that stay inside the ui-protocol subset.
    """
    for op in contract.operations:
        where = f"{contract.component}.{op.name or '<unnamed>'}"
        if not op.name:
            raise GeneratorError(f"{contract.component}: operation is missing a name")
        if op.kind not in _VALID_OPERATION_KINDS:
            raise GeneratorError(
                f"{where}: invalid operation kind {op.kind!r} "
                f"(must be one of {sorted(_VALID_OPERATION_KINDS)})"
            )
        assert_supported_schema(op.input, where=f"{where}.input")
        assert_supported_schema(op.output, where=f"{where}.output")


def _pascal(name: str) -> str:
    """``list`` → ``List``; ``get_summary`` / ``get-summary`` → ``GetSummary``."""
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[-_\s]+", name) if part)


def emit_contract_types(contract: DataContract) -> str:
    """Emit TypeScript interfaces for a contract's operation input/output.

    Reuses the ui_protocol TS emitter (no second type system). Each operation
    yields ``<Component><Op>Input`` / ``<Component><Op>Output`` interfaces. An
    empty (or non-object) schema becomes an empty object interface; v1 contract
    op bodies are expected to be objects (request/response shapes).
    """
    schemas: list[Schema] = []
    for op in contract.operations:
        op_name = _pascal(op.name)
        for suffix, body in (("Input", op.input), ("Output", op.output)):
            obj = (
                body
                if body.get("type") == "object"
                else {"type": "object", "properties": body.get("properties", {})}
            )
            schemas.append(Schema(title=f"{contract.component}{op_name}{suffix}", body=obj))
    return emit_typescript(schemas)


def load_components(root: Path | None = None) -> list[CanvasComponentSpec]:
    """Load every ``*.props.schema.json`` under ``root``.

    The canvas component name is derived from the schema's ``title``
    (stripping the ``Props`` suffix): ``DataTableProps`` → ``DataTable``.

    Initiative #6 (caching): each schema payload is loaded via
    :func:`forge.codegen._schema_cache.load_json_schema` so repeat
    invocations during a single codegen pass parse each file once,
    not once per call site.
    """
    root = root or DEFAULT_SCHEMA_ROOT
    components: list[CanvasComponentSpec] = []
    for path in sorted(root.glob("*.props.schema.json")):
        raw = load_json_schema(path)
        title = raw.get("title") or ""
        if not title.endswith("Props"):
            raise GeneratorError(
                f"{path}: canvas props schema title must end with 'Props' (got {title!r})"
            )
        name = title[: -len("Props")]
        # Optional sibling data contract: ``<Component>.contract.json`` next to
        # the props schema. Absent ⇒ pure-UI component.
        contract: DataContract | None = None
        contract_path = path.parent / f"{name}.contract.json"
        if contract_path.is_file():
            contract = load_data_contract(contract_path)
            if contract.component != name:
                raise GeneratorError(
                    f"{contract_path}: contract component {contract.component!r} "
                    f"does not match the props-derived component name {name!r}"
                )
            validate_data_contract(contract)
        components.append(
            CanvasComponentSpec(
                name=name,
                props_schema=raw,
                description=str(raw.get("description") or ""),
                contract=contract,
            )
        )
    return components


def _contract_to_manifest(contract: DataContract) -> dict[str, Any]:
    """Serialize a contract's operations for ``canvas.manifest.json``."""
    return {
        "operations": [
            {
                "name": op.name,
                "kind": op.kind,
                "input": op.input,
                "output": op.output,
            }
            for op in contract.operations
        ]
    }


def build_manifest(components: list[CanvasComponentSpec]) -> dict[str, Any]:
    """Produce ``canvas.manifest.json`` — one entry per component.

    The manifest is **version 2** only when at least one component carries a
    data contract; otherwise it stays **version 1** so contract-less projects
    (every shipped component today) emit a byte-identical v1 manifest and old
    readers are unaffected. A v2 reader treats a missing ``contract`` key as a
    pure-UI component.
    """
    has_contract = any(c.contract is not None for c in components)
    version = 2 if has_contract else 1
    schema_url = f"https://forge.dev/schemas/canvas-manifest-v{version}.json"

    entries: dict[str, Any] = {}
    for c in components:
        entry: dict[str, Any] = {
            "description": c.description,
            "props_schema": c.props_schema,
        }
        if c.contract is not None:
            entry["contract"] = _contract_to_manifest(c.contract)
        entries[c.name] = entry

    return {
        "$schema": schema_url,
        "version": version,
        "components": entries,
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

"""TypeSpec compiler bridge for the forge domain DSL.

Users who want a richer schema language than the YAML DSL can author
entities in ``.tsp`` files and let forge invoke the TypeSpec compiler
to emit OpenAPI + JSON Schema representations. Those representations
feed the same per-language emitters used by the YAML path, so adopting
TypeSpec is additive — projects mixing ``domain/*.yaml`` and
``domain/*.tsp`` get a merged view.

Requires Node 20+ and ``@typespec/compiler`` / ``@typespec/openapi3``
installed on the user's machine. ``typespec_available()`` returns
``False`` when the toolchain is missing so callers can skip silently.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def typespec_available() -> bool:
    """``True`` when ``npx`` is on PATH (needed to drive ``tsp``)."""
    return shutil.which("npx") is not None or shutil.which("tsp") is not None


@dataclass(frozen=True)
class TypespecEmitOutput:
    """The artefacts a successful compile produces."""

    openapi_yaml: str
    """Raw OpenAPI 3.1 YAML as emitted by ``@typespec/openapi3``."""

    openapi_spec: dict[str, Any] = field(default_factory=dict)
    """Parsed OpenAPI document for downstream processing."""


class TypespecUnavailable(RuntimeError):
    """Raised when the TypeSpec toolchain is not installed."""


def compile_tsp(source_dir: Path, *, entry: str | None = None) -> TypespecEmitOutput:
    """Run ``tsp compile`` on ``source_dir`` and return the OpenAPI output.

    ``entry`` is the main ``.tsp`` file (relative to ``source_dir``); if
    omitted, TypeSpec picks ``main.tsp`` by convention.

    Raises ``TypespecUnavailable`` when the compiler isn't on PATH, and
    ``RuntimeError`` when compilation fails.
    """
    if not typespec_available():
        raise TypespecUnavailable(
            "TypeSpec toolchain not found. Install with "
            "`npm install -g @typespec/compiler @typespec/openapi3`."
        )

    tsp_bin = shutil.which("tsp") or "npx"
    prefix_args: list[str] = [tsp_bin]
    if tsp_bin.endswith("npx") or tsp_bin.endswith("npx.cmd"):
        prefix_args = [tsp_bin, "--yes", "tsp"]

    with tempfile.TemporaryDirectory(prefix="forge-tsp-") as tmp:
        out_dir = Path(tmp)
        cmd = [
            *prefix_args,
            "compile",
            entry or ".",
            "--emit",
            "@typespec/openapi3",
            "--output-dir",
            str(out_dir),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(source_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"tsp compile failed (exit {proc.returncode}):\n"
                f"stdout: {proc.stdout[:500]}\nstderr: {proc.stderr[:500]}"
            )

        # @typespec/openapi3 emits under <out>/@typespec/openapi3/.
        candidates = list(out_dir.rglob("openapi.yaml")) + list(out_dir.rglob("openapi.json"))
        if not candidates:
            raise RuntimeError(
                "tsp compile produced no openapi artefact. Check that "
                "@typespec/openapi3 is enabled in the source's tspconfig.yaml."
            )
        artefact = candidates[0]

    yaml_text = artefact.read_text(encoding="utf-8") if artefact.exists() else ""
    spec: dict[str, Any] = {}
    if artefact.suffix == ".json":
        spec = json.loads(yaml_text) if yaml_text else {}
    else:
        # Lazy-import PyYAML so this stays importable even if PyYAML
        # isn't installed (forge's own dep list has it, but the TypeSpec
        # sidecar path could run in bare environments).
        try:
            import yaml  # noqa: PLC0415
        except ImportError:
            yaml = None  # type: ignore[assignment]
        if yaml is not None and yaml_text:
            spec = yaml.safe_load(yaml_text) or {}

    return TypespecEmitOutput(openapi_yaml=yaml_text, openapi_spec=spec)


def extract_entities(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull entity definitions out of a TypeSpec-emitted OpenAPI document.

    Looks at ``components.schemas.*`` and returns simplified dicts
    matching the shape the YAML DSL uses so the same emitters (Pydantic,
    Zod, sqlx, OpenAPI) can consume either source.
    """
    schemas = (spec.get("components") or {}).get("schemas") or {}
    entities: list[dict[str, Any]] = []
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        if schema.get("type") != "object":
            continue
        props = schema.get("properties") or {}
        required = set(schema.get("required") or ())
        fields: list[dict[str, Any]] = []
        for prop_name, prop_schema in props.items():
            if not isinstance(prop_schema, dict):
                continue
            fields.append(_openapi_prop_to_yaml_field(prop_name, prop_schema, required))
        entities.append(
            {
                "name": name,
                "plural": _infer_plural(name),
                "description": str(schema.get("description") or ""),
                "fields": fields,
            }
        )
    return entities


def _openapi_prop_to_yaml_field(
    name: str, schema: dict[str, Any], required: set[str]
) -> dict[str, Any]:
    """Translate one OpenAPI property into a YAML-DSL-style field spec."""
    field: dict[str, Any] = {"name": name}
    if name not in required:
        field["optional"] = True

    fmt = schema.get("format")
    ty = schema.get("type")
    if fmt == "uuid":
        field["type"] = "uuid"
    elif fmt in ("date-time", "date-time-offset"):
        field["type"] = "datetime"
    elif fmt == "date":
        field["type"] = "date"
    elif ty == "string":
        field["type"] = "string"
        if "minLength" in schema:
            field["min_length"] = schema["minLength"]
        if "maxLength" in schema:
            field["max_length"] = schema["maxLength"]
    elif ty == "integer":
        field["type"] = "integer"
    elif ty == "number":
        field["type"] = "number"
    elif ty == "boolean":
        field["type"] = "boolean"
    elif ty == "array":
        field["type"] = "array"
        inner = schema.get("items") or {}
        field["of"] = inner.get("type") or "string"
    elif ty == "object":
        field["type"] = "json"
    else:
        field["type"] = "string"  # fallback

    if "$ref" in schema:
        # Could be an enum or related entity; emit as enum ref for now.
        ref = str(schema["$ref"])
        target = ref.split("/")[-1]
        field["type"] = "enum"
        field["enum"] = target
    return field


def _infer_plural(name: str) -> str:
    snake = _to_snake(name)
    if snake.endswith("y") and len(snake) > 1 and snake[-2] not in "aeiou":
        return snake[:-1] + "ies"
    if snake.endswith(("s", "x", "z", "ch", "sh")):
        return snake + "es"
    return snake + "s"


def _to_snake(name: str) -> str:
    out: list[str] = []
    for i, c in enumerate(name):
        if c.isupper() and i > 0 and not name[i - 1].isupper():
            out.append("_")
        out.append(c.lower())
    return "".join(out)

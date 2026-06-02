"""Brownfield OpenAPI binding primitives (Phase 5).

Two pure cores used when binding a component's data contract to an existing
OpenAPI backend:

* :func:`flatten_refs` — inline internal ``$ref`` chains
  (``#/components/schemas/<Name>``) so an external schema reduces to the
  ui-protocol subset the emitters/validators understand. Cyclic or
  unresolvable refs fail loud.
* the **transform DSL** (:func:`apply_transform` + :func:`coerce_value`) —
  maps an upstream payload onto a contract operation's shape via field renames
  (dotted source paths) + a closed whitelist of scalar coercions. Anything
  outside the whitelist / a missing source path fails loud
  (``GeneratorError`` → surfaced as ``FEATURE_CONTRACT_VIOLATION`` by the caller).

Out of scope for v1 (documented): array-element path remapping (``items[].id``),
field synthesis, conditionals.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import tomlkit

from forge.errors import FEATURE_CONTRACT_VIOLATION, GeneratorError, PluginError

if TYPE_CHECKING:
    from forge.codegen.canvas_contract import DataContract

_REF_PREFIX = "#/components/schemas/"
_COERCIONS = ("int", "float", "str", "bool")


def flatten_refs(
    schema: Any, *, components: dict[str, Any], _seen: frozenset[str] = frozenset()
) -> Any:
    """Return ``schema`` with internal ``$ref``s inlined from ``components``.

    Only ``#/components/schemas/<Name>`` refs are supported; any other ref form,
    an unresolvable name, or a cycle raises ``GeneratorError``.
    """
    if not isinstance(schema, dict):
        return schema

    ref = schema.get("$ref")
    if ref is not None:
        if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX):
            raise GeneratorError(
                f"Unsupported $ref {ref!r}; only {_REF_PREFIX}<Name> is supported."
            )
        name = ref[len(_REF_PREFIX) :]
        if name in _seen:
            raise GeneratorError(f"Cyclic (circular) $ref detected resolving {name!r}.")
        target = components.get(name)
        if target is None:
            raise GeneratorError(f"Cannot resolve $ref: {name!r} not in components.schemas.")
        return flatten_refs(target, components=components, _seen=_seen | {name})

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            out[key] = flatten_refs(value, components=components, _seen=_seen)
        elif isinstance(value, list):
            out[key] = [
                flatten_refs(item, components=components, _seen=_seen)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def coerce_value(value: Any, kind: str) -> Any:
    """Apply one whitelisted scalar coercion. Unknown kind / un-coercible value
    → ``GeneratorError`` (so the caller maps it to FEATURE_CONTRACT_VIOLATION)."""
    if kind in ("int", "float"):
        try:
            return int(value) if kind == "int" else float(value)
        except (ValueError, TypeError) as exc:
            raise GeneratorError(f"Cannot coerce {value!r} to {kind}: {exc}") from exc
    if kind == "str":
        return str(value)
    if kind == "bool":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
        raise GeneratorError(f"Cannot coerce {value!r} to bool.")
    raise GeneratorError(f"Unknown coercion {kind!r}; allowed: {list(_COERCIONS)}.")


def _get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise GeneratorError(f"Transform source path {path!r} not found (missing/absent).")
        cur = cur[part]
    return cur


def apply_transform(upstream: dict[str, Any], transform: dict[str, Any]) -> dict[str, Any]:
    """Map ``upstream`` onto a contract shape per the transform DSL.

    Each ``dest`` maps to either a dotted source-path string (rename) or a
    ``{"from": <path>, "coerce": <kind>}`` table (rename + coercion).

    v1 limits (documented, like array-element source paths): ``dest`` keys are
    flat (a literal output key — ``"user.id"`` does NOT nest into
    ``{"user": {"id": ...}}``); array-element remapping (``items[].id``) and
    field synthesis are out of scope.
    """
    if not isinstance(transform, dict):
        raise GeneratorError(f"transform must be a table, got {type(transform).__name__}.")
    out: dict[str, Any] = {}
    for dest, rule in transform.items():
        if isinstance(rule, str):
            out[dest] = _get_path(upstream, rule)
        elif isinstance(rule, dict):
            src = rule.get("from")
            if not isinstance(src, str):
                raise GeneratorError(f"Transform rule for {dest!r} needs a 'from' path string.")
            value = _get_path(upstream, src)
            coerce = rule.get("coerce")
            out[dest] = coerce_value(value, coerce) if coerce else value
        else:
            raise GeneratorError(
                f"Transform rule for {dest!r} must be a path string or a {{from, coerce}} table."
            )
    return out


# ---------------------------------------------------------------------------
# Binding validation: contract operations <-> OpenAPI operationIds
# ---------------------------------------------------------------------------


_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _media_schema(content: Any) -> dict[str, Any] | None:
    """First media-type schema under an OpenAPI ``content`` block."""
    if not isinstance(content, dict):
        return None
    for media in content.values():
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    return None


def _select_2xx(responses: Any) -> dict[str, Any] | None:
    """Pick a success response: prefer 200/201, then any 2xx, then 2XX/default."""
    if not isinstance(responses, dict):
        return None
    for pref in ("200", "201"):
        if isinstance(responses.get(pref), dict):
            return responses[pref]
    for code, entry in responses.items():
        if isinstance(code, str) and code.startswith("2") and isinstance(entry, dict):
            return entry
    for code in ("2XX", "default"):
        if isinstance(responses.get(code), dict):
            return responses[code]
    return None


def _schema_has_path(schema: Any, path: str) -> bool:
    """True if a dotted property ``path`` resolves through ``schema.properties``."""
    cur = schema
    for part in path.split("."):
        if not isinstance(cur, dict):
            return False
        props = cur.get("properties")
        if not isinstance(props, dict) or part not in props:
            return False
        cur = props[part]
    return True


def index_operations(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Parse an OpenAPI doc into ``operationId -> {request, response}`` schemas.

    Request/response schemas are flattened (``$ref``s inlined). Only true HTTP
    methods are scanned; operations without an ``operationId`` are skipped. Any
    success (2xx) response with content is used. Robust to malformed nodes
    (non-dict ``paths``/``components``/``responses``).
    """
    if not isinstance(spec, dict):
        return {}
    components_node = spec.get("components")
    schemas = components_node.get("schemas") if isinstance(components_node, dict) else None
    components = schemas if isinstance(schemas, dict) else {}
    paths = spec.get("paths")
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(paths, dict):
        return index
    for methods in paths.values():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if not isinstance(op_id, str) or not op_id:
                continue
            req = None
            request_body = op.get("requestBody")
            if isinstance(request_body, dict):
                req = _media_schema(request_body.get("content"))
            resp_entry = _select_2xx(op.get("responses"))
            resp = (
                _media_schema(resp_entry.get("content")) if isinstance(resp_entry, dict) else None
            )
            index[op_id] = {
                "request": flatten_refs(req, components=components) if req else {},
                "response": flatten_refs(resp, components=components) if resp else {},
            }
    return index


def validate_bindings(
    contract: DataContract, bindings: dict[str, Any], spec: dict[str, Any]
) -> list[str]:
    """Return binding violations for a contract against an OpenAPI spec + mapping.

    Violations: a contract op has no binding; its ``operation_id`` is unknown; a
    transform rule's source path doesn't resolve in the bound response schema;
    or a required output field is satisfied by neither a (valid) transform dest
    nor an upstream response property.

    Note (v1): satisfaction is *shape-presence* by field name — it does not
    propagate the upstream's own ``required`` set (an upstream-optional property
    still counts). Documented limitation.
    """
    index = index_operations(spec)
    violations: list[str] = []
    for op in contract.operations:
        binding = bindings.get(op.name)
        if not isinstance(binding, dict):
            violations.append(f"contract operation {op.name!r} has no binding")
            continue
        op_id = binding.get("operation_id")
        if op_id not in index:
            violations.append(f"binding for {op.name!r} references unknown operationId {op_id!r}")
            continue
        response_schema = index[op_id]["response"]
        transform = binding.get("response", {})
        transform = transform if isinstance(transform, dict) else {}

        # Transform dests count toward satisfaction only if their source path
        # actually resolves in the upstream response schema.
        valid_dests: set[str] = set()
        for dest, rule in transform.items():
            src = rule.get("from") if isinstance(rule, dict) else rule
            if not isinstance(src, str):
                violations.append(
                    f"binding {op.name!r}: transform rule {dest!r} has no source path"
                )
                continue
            if _schema_has_path(response_schema, src):
                valid_dests.add(dest)
            else:
                violations.append(
                    f"binding {op.name!r}: transform source path {src!r} not found in "
                    f"operationId {op_id!r} response"
                )

        upstream_props = (
            set((response_schema.get("properties") or {}).keys())
            if isinstance(response_schema, dict)
            else set()
        )
        required = set(op.output.get("required", [])) if isinstance(op.output, dict) else set()
        missing = sorted(required - (valid_dests | upstream_props))
        if missing:
            violations.append(
                f"contract operation {op.name!r} output requires {missing} "
                f"not satisfied by operationId {op_id!r} (after transform)"
            )
    return violations


def assert_bindings_valid(
    contract: DataContract, bindings: dict[str, Any], spec: dict[str, Any]
) -> None:
    """Raise ``FEATURE_CONTRACT_VIOLATION`` if any binding is invalid."""
    violations = validate_bindings(contract, bindings, spec)
    if violations:
        # PluginError (not the GeneratorError base) so the CLI maps
        # FEATURE_CONTRACT_VIOLATION to exit code 6, per the plan's error table.
        raise PluginError(
            "contract binding validation failed:\n  - " + "\n  - ".join(violations),
            code=FEATURE_CONTRACT_VIOLATION,
        )


# ---------------------------------------------------------------------------
# Mapping artifact: the editable [contract_bindings] TOML
# ---------------------------------------------------------------------------


def propose_bindings(contract: DataContract, spec: dict[str, Any]) -> dict[str, Any]:
    """Propose contract-op → operationId bindings (best-effort, user-editable).

    Each contract operation gets an entry whose ``operation_id`` is the first
    upstream operationId containing the op name (case-insensitive), or ``""``
    when no candidate matches — the user fills/edits it. ``response`` is an
    empty transform table for the user to populate.
    """
    op_ids = sorted(index_operations(spec).keys())
    proposed: dict[str, Any] = {}
    for op in contract.operations:
        match = ""
        for oid in op_ids:
            if op.name.lower() in oid.lower():
                match = oid
                break
        proposed[op.name] = {"operation_id": match, "response": {}}
    return proposed


def bindings_to_toml(bindings: dict[str, Any]) -> str:
    """Serialize a bindings mapping to a ``[contract_bindings]`` TOML string."""
    doc = tomlkit.document()
    root = tomlkit.table()
    for op_name, binding in bindings.items():
        entry = tomlkit.table()
        entry["operation_id"] = str(binding.get("operation_id", ""))
        response = tomlkit.table()
        for key, value in (binding.get("response") or {}).items():
            response[str(key)] = value
        entry["response"] = response
        root[str(op_name)] = entry
    doc["contract_bindings"] = root
    return tomlkit.dumps(doc)


def bindings_from_toml(text: str) -> dict[str, Any]:
    """Parse a ``[contract_bindings]`` TOML string into the bindings mapping
    that :func:`validate_bindings` consumes."""
    doc = tomlkit.parse(text)
    root = doc.get("contract_bindings", {})
    out: dict[str, Any] = {}
    if not isinstance(root, dict):
        return out
    for op_name, binding in root.items():
        if not isinstance(binding, dict):
            continue
        response = binding.get("response") or {}
        out[str(op_name)] = {
            "operation_id": str(binding.get("operation_id", "")),
            "response": {str(k): v for k, v in response.items()}
            if isinstance(response, dict)
            else {},
        }
    return out


# ---------------------------------------------------------------------------
# Transform DSL -> TypeScript adapter (plan §E)
# ---------------------------------------------------------------------------

# int/float -> Number, str -> String (JS semantics match closely enough);
# bool -> forgeBool (a helper that matches the DSL's truthy set, NOT JS
# Boolean(), which would make "false"/"0" truthy).
_TS_COERCE = {"int": "Number", "float": "Number", "str": "String", "bool": "forgeBool"}


def _pascal_op(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in name.replace("-", "_").split("_") if p)


def _ts_path(path: str) -> str:
    # json.dumps each segment so a hand-edited path with quotes/specials can't
    # produce invalid TS or inject code.
    return "upstream" + "".join(f"[{json.dumps(part)}]" for part in path.split("."))


def _ts_key(dest: str) -> str:
    """A safe TS object key: bare for valid identifiers, quoted otherwise."""
    s = str(dest)
    if s and (s[0].isalpha() or s[0] in "_$") and all(c.isalnum() or c in "_$" for c in s):
        return s
    return json.dumps(s)


def transform_adapter_prelude() -> str:
    """Shared TS helpers the generated transform adapters depend on.

    ``forgeBool`` mirrors the Python ``coerce_value`` bool semantics (true/1/yes
    are true, everything else false) so the runtime adapter agrees with the
    build-time binding validation — unlike JS ``Boolean()``.
    """
    return (
        "// Shared brownfield transform helpers (forge). Do not edit by hand.\n"
        "export function forgeBool(v: unknown): boolean {\n"
        '  return v === true || v === 1 || v === "true" || v === "1" || v === "yes";\n'
        "}\n"
    )


def emit_transform_adapter(component: str, op_name: str, transform: dict[str, Any]) -> str:
    """Emit a TS function mapping an upstream payload onto the contract shape.

    Renames become (escaped) bracket-path reads; coercions map to
    ``Number``/``String``/``forgeBool`` (see :func:`transform_adapter_prelude`).
    Object keys are emitted as string literals so non-identifier dest names are
    valid. An empty transform emits a pass-through. The function is named
    ``map<Component><Op>Response``.
    """
    fn = f"map{component}{_pascal_op(op_name)}Response"
    header = "// Generated transform adapter (forge brownfield binding). Do not edit by hand."
    if not transform:
        return f"{header}\nexport function {fn}(upstream: any): any {{\n  return upstream;\n}}\n"

    lines = [header, f"export function {fn}(upstream: any) {{", "  return {"]
    for dest, rule in transform.items():
        if isinstance(rule, dict):
            src = str(rule.get("from", ""))
            coerce = rule.get("coerce")
        else:
            src, coerce = str(rule), None
        expr = _ts_path(src)
        if coerce:
            wrap = _TS_COERCE.get(coerce)
            if wrap is None:
                raise GeneratorError(f"Unknown coercion {coerce!r} for TS adapter.")
            expr = f"{wrap}({expr})"
        lines.append(f"    {_ts_key(dest)}: {expr},")
    lines += ["  };", "}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-contract bindings document (one mapping artifact per project)
# ---------------------------------------------------------------------------


def build_bindings_document(named_contracts: dict[str, DataContract], spec: dict[str, Any]) -> str:
    """Aggregate per-component binding proposals into one TOML artifact.

    Sections are ``[contract_bindings.<Component>.<op>]`` so a single
    project-level file covers every selected contract-bearing component.
    """
    doc = tomlkit.document()
    root = tomlkit.table()
    for component, contract in named_contracts.items():
        comp_tbl = tomlkit.table()
        for op_name, binding in propose_bindings(contract, spec).items():
            entry = tomlkit.table()
            entry["operation_id"] = str(binding.get("operation_id", ""))
            response = tomlkit.table()
            for key, value in (binding.get("response") or {}).items():
                response[str(key)] = value
            entry["response"] = response
            comp_tbl[str(op_name)] = entry
        root[str(component)] = comp_tbl
    doc["contract_bindings"] = root
    return tomlkit.dumps(doc)


def parse_bindings_document(text: str) -> dict[str, dict[str, Any]]:
    """Parse a multi-component bindings document into ``{component: bindings}``."""
    doc = tomlkit.parse(text)
    root = doc.get("contract_bindings", {})
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(root, dict):
        return out
    for component, comp_tbl in root.items():
        if not isinstance(comp_tbl, dict):
            continue
        bindings: dict[str, Any] = {}
        for op_name, binding in comp_tbl.items():
            if not isinstance(binding, dict):
                continue
            response = binding.get("response") or {}
            bindings[str(op_name)] = {
                "operation_id": str(binding.get("operation_id", "")),
                "response": {str(k): v for k, v in response.items()}
                if isinstance(response, dict)
                else {},
            }
        out[str(component)] = bindings
    return out


def validate_bindings_document(
    named_contracts: dict[str, DataContract],
    document: dict[str, dict[str, Any]],
    spec: dict[str, Any],
) -> list[str]:
    """Validate every component's bindings; violations are tagged ``[Component]``."""
    violations: list[str] = []
    for component, contract in named_contracts.items():
        bindings = document.get(component, {})
        violations.extend(f"[{component}] {v}" for v in validate_bindings(contract, bindings, spec))
    return violations


def load_openapi_spec(path: str) -> dict[str, Any]:
    """Read + parse an OpenAPI document from a local file (JSON or YAML).

    URL fetching is intentionally out of scope here (a network concern the
    caller can layer on); a missing/invalid file fails loud.
    """
    p = Path(path)
    if not p.is_file():
        raise GeneratorError(f"OpenAPI spec not found: {path}")
    text = p.read_text(encoding="utf-8")
    try:
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml  # noqa: PLC0415

            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except Exception as exc:  # noqa: BLE001 — surface any parse error uniformly
        raise GeneratorError(f"Failed to parse OpenAPI spec {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GeneratorError(f"OpenAPI spec {path} must be a mapping at the top level.")
    return data

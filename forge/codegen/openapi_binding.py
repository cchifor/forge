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

from typing import TYPE_CHECKING, Any

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

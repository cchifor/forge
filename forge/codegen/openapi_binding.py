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

from forge.errors import FEATURE_CONTRACT_VIOLATION, GeneratorError

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


def _media_schema(content: Any) -> dict[str, Any] | None:
    """First media-type schema under an OpenAPI ``content`` block."""
    if not isinstance(content, dict):
        return None
    for media in content.values():
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media["schema"]
    return None


def index_operations(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Parse an OpenAPI doc into ``operationId -> {request, response}`` schemas.

    Request/response schemas are flattened (``$ref``s inlined) so downstream
    shape checks see the ui-protocol subset. Operations without an
    ``operationId`` are skipped.
    """
    components = (spec.get("components") or {}).get("schemas") or {}
    index: dict[str, dict[str, Any]] = {}
    for methods in (spec.get("paths") or {}).values():
        if not isinstance(methods, dict):
            continue
        for op in methods.values():
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId")
            if not isinstance(op_id, str) or not op_id:
                continue
            req = None
            request_body = op.get("requestBody")
            if isinstance(request_body, dict):
                req = _media_schema(request_body.get("content"))
            resp = None
            responses = op.get("responses") or {}
            for code in ("200", "201", "2XX", "default"):
                entry = responses.get(code)
                if isinstance(entry, dict):
                    resp = _media_schema(entry.get("content"))
                    if resp is not None:
                        break
            index[op_id] = {
                "request": flatten_refs(req, components=components) if req else {},
                "response": flatten_refs(resp, components=components) if resp else {},
            }
    return index


def _available_keys(transform: Any, upstream_schema: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(transform, dict):
        keys |= {str(k) for k in transform}
    if isinstance(upstream_schema, dict):
        props = upstream_schema.get("properties")
        if isinstance(props, dict):
            keys |= {str(k) for k in props}
    return keys


def validate_bindings(
    contract: DataContract, bindings: dict[str, Any], spec: dict[str, Any]
) -> list[str]:
    """Return binding violations for a contract against an OpenAPI spec + mapping.

    A violation is raised (by the caller) when: a contract operation has no
    binding, its ``operation_id`` is absent from the spec, or its required
    output fields are not satisfied by the bound operation's response (after
    applying the per-binding ``response`` transform's renames).
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
        required = set(op.output.get("required", [])) if isinstance(op.output, dict) else set()
        missing = sorted(required - _available_keys(transform, response_schema))
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
        raise GeneratorError(
            "contract binding validation failed:\n  - " + "\n  - ".join(violations),
            code=FEATURE_CONTRACT_VIOLATION,
        )

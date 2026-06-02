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

from typing import Any

from forge.errors import GeneratorError

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

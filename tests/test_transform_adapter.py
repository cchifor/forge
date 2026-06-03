"""The transform DSL compiles to a TS adapter (plan §E).

emit_transform_adapter turns a binding's response transform into a TS function
that maps an upstream payload onto the contract shape (renames via bracket
paths, coercions via Number/String/Boolean), so the generated Vue client can
adapt an external response without hand-written glue.
"""

from __future__ import annotations

from forge.codegen.openapi_binding import emit_transform_adapter


def test_emits_rename_and_coercion() -> None:
    ts = emit_transform_adapter(
        "EntityList", "list", {"items": "data", "count": {"from": "total", "coerce": "int"}}
    )
    assert "export function mapEntityListListResponse" in ts
    assert 'items: upstream["data"]' in ts
    assert 'count: Number(upstream["total"])' in ts


def test_dotted_source_path_becomes_bracket_chain() -> None:
    ts = emit_transform_adapter("E", "get", {"value": "data.inner.v"})
    assert 'value: upstream["data"]["inner"]["v"]' in ts


def test_bool_and_str_coercions() -> None:
    ts = emit_transform_adapter(
        "E", "get", {"flag": {"from": "f", "coerce": "bool"}, "name": {"from": "n", "coerce": "str"}}
    )
    # bool uses a helper matching the DSL semantics, not JS Boolean() (which
    # would make "false"/"0" truthy).
    assert 'forgeBool(upstream["f"])' in ts
    assert 'name: String(upstream["n"])' in ts


def test_non_identifier_dest_key_is_quoted() -> None:
    ts = emit_transform_adapter("E", "get", {"data-x": "a"})
    assert '"data-x": upstream["a"]' in ts


def test_source_segment_is_escaped() -> None:
    # A quote in a (hand-edited) source path must be escaped, not break the TS.
    ts = emit_transform_adapter("E", "get", {"v": 'a"b'})
    assert r'["a\"b"]' in ts
    assert '["a"b"]' not in ts  # never the unescaped/invalid form


def test_prelude_bool_helper_matches_dsl() -> None:
    from forge.codegen.openapi_binding import transform_adapter_prelude

    prelude = transform_adapter_prelude()
    assert "export function forgeBool" in prelude
    assert '"true"' in prelude and '"1"' in prelude


def test_empty_transform_emits_passthrough() -> None:
    ts = emit_transform_adapter("E", "get", {})
    assert "mapEGetResponse" in ts
    assert "return upstream" in ts

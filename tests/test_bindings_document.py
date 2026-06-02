"""Multi-contract `[contract_bindings]` document (Phase 5 wiring).

A generated brownfield project has one mapping artifact covering every selected
contract-bearing component. build_bindings_document aggregates per-component
proposals; parse/validate round-trip it.
"""

from __future__ import annotations

from forge.codegen.canvas_contract import ContractOperation, DataContract
from forge.codegen.openapi_binding import (
    build_bindings_document,
    parse_bindings_document,
    validate_bindings_document,
)

_SPEC = {"paths": {"/i": {"get": {"operationId": "listItems", "responses": {}}}}}
_C1 = DataContract(component="EntityList", operations=(
    ContractOperation(name="list", kind="read", input={}, output={}),))
_C2 = DataContract(component="StatCard", operations=())


def test_build_document_per_component_sections() -> None:
    text = build_bindings_document({"EntityList": _C1, "StatCard": _C2}, _SPEC)
    assert "[contract_bindings.EntityList.list]" in text
    assert 'operation_id = "listItems"' in text


def test_round_trip() -> None:
    text = build_bindings_document({"EntityList": _C1}, _SPEC)
    parsed = parse_bindings_document(text)
    assert parsed["EntityList"]["list"]["operation_id"] == "listItems"


def test_validate_document_aggregates_violations() -> None:
    # An unbound required op surfaces a violation tagged with the component.
    c = DataContract(component="EntityList", operations=(
        ContractOperation(name="list", kind="read", input={},
                          output={"type": "object", "properties": {"x": {}}, "required": ["x"]}),))
    parsed = {"EntityList": {}}  # no binding for list
    violations = validate_bindings_document({"EntityList": c}, parsed, _SPEC)
    assert any("EntityList" in v and "list" in v for v in violations)

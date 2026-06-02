"""Tests for emitting TypeScript types from a component's data contract.

The contract's operation input/output schemas are emitted as TS interfaces (via
the existing ``ui_protocol`` emitter — no second type system) so a generated
``.vue`` imports a typed surface; a later contract change that the user's
customization no longer satisfies is then caught by ``vue-tsc`` at build time.
"""

from __future__ import annotations

from forge.codegen.canvas_contract import (
    ContractOperation,
    DataContract,
    emit_contract_types,
)


def _contract() -> DataContract:
    return DataContract(
        component="EntityList",
        operations=(
            ContractOperation(
                name="list",
                kind="read",
                input={"type": "object", "properties": {"page": {"type": "integer"}}},
                output={
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}},
                        "total": {"type": "integer"},
                    },
                    "required": ["items"],
                },
            ),
        ),
    )


def test_emits_input_and_output_interfaces() -> None:
    ts = emit_contract_types(_contract())
    assert "export interface EntityListListInput" in ts
    assert "export interface EntityListListOutput" in ts


def test_optional_and_required_fields() -> None:
    ts = emit_contract_types(_contract())
    # `page` is not required -> optional; `items` is required.
    assert "page?: number" in ts
    assert "items: Array<string>" in ts


def test_multiword_operation_name_pascalcased() -> None:
    c = DataContract(
        component="Report",
        operations=(
            ContractOperation(name="get_summary", kind="read", input={}, output={}),
        ),
    )
    ts = emit_contract_types(c)
    assert "ReportGetSummaryInput" in ts
    assert "ReportGetSummaryOutput" in ts


def test_pure_ui_contract_emits_header_only() -> None:
    ts = emit_contract_types(DataContract(component="StatCard", operations=()))
    # No operations -> no interfaces, but a stable generated-file header.
    assert "interface" not in ts
    assert "Generated" in ts

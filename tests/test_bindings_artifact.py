"""The brownfield mapping artifact (Phase 5 wiring).

`propose_bindings` generates a `[contract_bindings]` proposal (contract op →
upstream operationId, best-effort) that the user edits; `bindings_to_toml` /
`bindings_from_toml` round-trip it so it can be emitted as a fragment file and
re-parsed for `validate_bindings`.
"""

from __future__ import annotations

from forge.codegen.canvas_contract import ContractOperation, DataContract
from forge.codegen.openapi_binding import (
    bindings_from_toml,
    bindings_to_toml,
    propose_bindings,
)

_SPEC = {
    "paths": {
        "/items": {"get": {"operationId": "listItems", "responses": {}}},
        "/items/{id}": {"get": {"operationId": "getItem", "responses": {}}},
    }
}
_CONTRACT = DataContract(
    component="EntityList",
    operations=(
        ContractOperation(name="list", kind="read", input={}, output={}),
        ContractOperation(name="archive", kind="write", input={}, output={}),
    ),
)


class TestProposeBindings:
    def test_matches_operation_id_by_name_heuristic(self) -> None:
        proposed = propose_bindings(_CONTRACT, _SPEC)
        # "list" fuzzy-matches "listItems"; "archive" has no match → empty.
        assert proposed["list"]["operation_id"] == "listItems"
        assert proposed["archive"]["operation_id"] == ""
        # every op gets an (editable) response transform table.
        assert "response" in proposed["list"]


class TestTomlRoundTrip:
    def test_round_trips(self) -> None:
        proposed = propose_bindings(_CONTRACT, _SPEC)
        text = bindings_to_toml(proposed)
        assert "[contract_bindings.list]" in text
        assert 'operation_id = "listItems"' in text
        parsed = bindings_from_toml(text)
        assert parsed["list"]["operation_id"] == "listItems"
        assert "archive" in parsed

    def test_parsed_form_feeds_validate(self) -> None:
        # The parsed dict is shaped exactly as validate_bindings consumes.
        from forge.codegen.openapi_binding import validate_bindings

        text = bindings_to_toml({"list": {"operation_id": "listItems", "response": {}}})
        parsed = bindings_from_toml(text)
        # A no-required-output contract op → no violations with a valid op id.
        contract = DataContract(
            component="E",
            operations=(ContractOperation(name="list", kind="read", input={}, output={}),),
        )
        assert validate_bindings(contract, parsed, _SPEC) == []

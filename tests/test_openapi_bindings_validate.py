"""Brownfield binding validation (Phase 5 integration).

`index_operations` parses an OpenAPI spec into operationId → flattened
request/response schemas. `validate_bindings` checks that every contract
operation binds to a real operationId whose (post-transform) response shape
satisfies the contract op's required output — returning a list of violations
(the caller raises FEATURE_CONTRACT_VIOLATION).
"""

from __future__ import annotations

import pytest

from forge.codegen.canvas_contract import ContractOperation, DataContract
from forge.codegen.openapi_binding import (
    assert_bindings_valid,
    index_operations,
    validate_bindings,
)
from forge.errors import GeneratorError

_SPEC = {
    "paths": {
        "/items": {
            "get": {
                "operationId": "listItems",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ItemList"}
                            }
                        }
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "ItemList": {
                "type": "object",
                "properties": {
                    "data": {"type": "array", "items": {"type": "string"}},
                    "total": {"type": "integer"},
                },
                "required": ["data", "total"],
            }
        }
    },
}

_CONTRACT = DataContract(
    component="EntityList",
    operations=(
        ContractOperation(
            name="list",
            kind="read",
            input={},
            output={
                "type": "object",
                "properties": {"items": {"type": "array"}, "count": {"type": "integer"}},
                "required": ["items", "count"],
            },
        ),
    ),
)


class TestIndexOperations:
    def test_indexes_by_operation_id_with_flattened_response(self) -> None:
        idx = index_operations(_SPEC)
        assert "listItems" in idx
        resp = idx["listItems"]["response"]
        # $ref flattened to the ItemList object.
        assert resp["properties"]["total"] == {"type": "integer"}


class TestValidateBindings:
    def _bindings(self, **overrides):
        b = {"list": {"operation_id": "listItems", "response": {"items": "data", "count": "total"}}}
        b["list"].update(overrides)
        return b

    def test_valid_binding_no_violations(self) -> None:
        assert validate_bindings(_CONTRACT, self._bindings(), _SPEC) == []

    def test_unbound_required_op_is_violation(self) -> None:
        violations = validate_bindings(_CONTRACT, {}, _SPEC)
        assert any("no binding" in v and "list" in v for v in violations)

    def test_unknown_operation_id_is_violation(self) -> None:
        b = {"list": {"operation_id": "ghostOp", "response": {"items": "data", "count": "total"}}}
        violations = validate_bindings(_CONTRACT, b, _SPEC)
        assert any("ghostOp" in v for v in violations)

    def test_unsatisfied_required_field_is_violation(self) -> None:
        # transform only maps `items`; contract also requires `count`.
        b = {"list": {"operation_id": "listItems", "response": {"items": "data"}}}
        violations = validate_bindings(_CONTRACT, b, _SPEC)
        assert any("count" in v for v in violations)

    def test_assert_raises_on_violation(self) -> None:
        from forge.cli.main import _exit_code_for
        from forge.errors import PluginError

        with pytest.raises(GeneratorError) as exc:  # PluginError is a ForgeError
            assert_bindings_valid(_CONTRACT, {}, _SPEC)
        assert exc.value.code == "FEATURE_CONTRACT_VIOLATION"
        # Contract violation must map to exit code 6 (PluginError), not 2.
        assert isinstance(exc.value, PluginError)
        assert _exit_code_for(exc.value) == 6


class TestBindingRobustness:
    def test_202_response_is_indexed(self) -> None:
        spec = {
            "paths": {
                "/x": {"post": {"operationId": "doX", "responses": {"202": {"content": {
                    "application/json": {"schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}}}}}}
            }
        }
        idx = index_operations(spec)
        assert idx["doX"]["response"]["properties"]["ok"] == {"type": "boolean"}

    def test_malformed_spec_does_not_crash(self) -> None:
        assert index_operations({"paths": "nope"}) == {}
        assert index_operations({"paths": {"/x": {"get": {"operationId": "g", "responses": "bad"}}}}) == {"g": {"request": {}, "response": {}}}

    def test_non_http_method_key_not_indexed(self) -> None:
        # A path-item `parameters` (or extension) key with an operationId-like
        # dict must not be treated as an operation.
        spec = {"paths": {"/x": {"parameters": {"operationId": "notAnOp"}, "get": {"operationId": "realOp", "responses": {}}}}}
        idx = index_operations(spec)
        assert "realOp" in idx and "notAnOp" not in idx

    def test_transform_source_must_exist_in_response(self) -> None:
        spec = {"paths": {"/i": {"get": {"operationId": "listItems", "responses": {"200": {"content": {
            "application/json": {"schema": {"type": "object", "properties": {"data": {"type": "array"}}}}}}}}}}}
        contract = DataContract(component="E", operations=(ContractOperation(
            name="list", kind="read", input={},
            output={"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}),))
        # transform maps items <- a path that doesn't exist in the response.
        bindings = {"list": {"operation_id": "listItems", "response": {"items": "ghost.path"}}}
        violations = validate_bindings(contract, bindings, spec)
        assert any("ghost.path" in v or "source" in v.lower() for v in violations)

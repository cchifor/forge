"""Tests for the data-contract layer of the canvas component model.

A component's contract is a sibling ``<Component>.contract.json`` next to its
``<Component>.props.schema.json``. It declares named operations
(``kind: read|write|subscribe``) whose ``input``/``output`` schemas live in the
same JSON-Schema subset ``ui_protocol`` already emits. Absent contract ⇒ a
pure-UI component (empty data-dependency set), which is a legal state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.codegen.canvas_contract import (
    CanvasComponentSpec,
    DataContract,
    build_manifest,
    load_components,
    load_data_contract,
    validate_data_contract,
)
from forge.errors import GeneratorError

_PROPS = {
    "title": "EntityListProps",
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"],
    "additionalProperties": False,
}

_CONTRACT = {
    "component": "EntityList",
    "operations": [
        {
            "name": "list",
            "kind": "read",
            "input": {
                "type": "object",
                "properties": {"page": {"type": "integer"}},
            },
            "output": {
                "type": "object",
                "properties": {
                    "items": {"type": "array", "items": {"type": "string"}},
                    "total": {"type": "integer"},
                },
                "required": ["items"],
            },
        }
    ],
}


def _write_component(root: Path, name: str, props: dict, contract: dict | None) -> None:
    (root / f"{name}.props.schema.json").write_text(json.dumps(props), encoding="utf-8")
    if contract is not None:
        (root / f"{name}.contract.json").write_text(json.dumps(contract), encoding="utf-8")


class TestCanvasComponentSpecContractField:
    def test_contract_defaults_to_none(self) -> None:
        spec = CanvasComponentSpec(name="StatCard", props_schema=_PROPS)
        assert spec.contract is None  # pure-UI component is representable


class TestLoadDataContract:
    def test_parses_operations(self, tmp_path: Path) -> None:
        p = tmp_path / "EntityList.contract.json"
        p.write_text(json.dumps(_CONTRACT), encoding="utf-8")
        contract = load_data_contract(p)
        assert isinstance(contract, DataContract)
        assert contract.component == "EntityList"
        assert len(contract.operations) == 1
        op = contract.operations[0]
        assert op.name == "list"
        assert op.kind == "read"
        assert op.output["required"] == ["items"]

    def test_rejects_unknown_kind(self, tmp_path: Path) -> None:
        bad = {
            "component": "X",
            "operations": [{"name": "go", "kind": "delete", "input": {}, "output": {}}],
        }
        p = tmp_path / "X.contract.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(GeneratorError, match="kind"):
            validate_data_contract(load_data_contract(p))


class TestValidateDataContract:
    def test_accepts_in_subset_schema(self) -> None:
        validate_data_contract(load_data_contract_from_dict(_CONTRACT))  # no raise

    def test_rejects_out_of_subset_schema(self) -> None:
        bad = {
            "component": "X",
            "operations": [
                {
                    "name": "get",
                    "kind": "read",
                    "input": {},
                    # oneOf is on ui_protocol's documented out-of-scope list
                    "output": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                }
            ],
        }
        with pytest.raises(GeneratorError):
            validate_data_contract(load_data_contract_from_dict(bad))

    def test_rejects_ref_schema(self) -> None:
        bad = {
            "component": "X",
            "operations": [
                {
                    "name": "get",
                    "kind": "read",
                    "input": {},
                    "output": {"$ref": "#/components/schemas/Item"},
                }
            ],
        }
        with pytest.raises(GeneratorError):
            validate_data_contract(load_data_contract_from_dict(bad))


class TestLoadComponentsWithContract:
    def test_loads_sibling_contract(self, tmp_path: Path) -> None:
        _write_component(tmp_path, "EntityList", _PROPS, _CONTRACT)
        comps = {c.name: c for c in load_components(tmp_path)}
        assert comps["EntityList"].contract is not None
        assert comps["EntityList"].contract.operations[0].name == "list"

    def test_component_without_contract_is_pure_ui(self, tmp_path: Path) -> None:
        _write_component(tmp_path, "StatCard", {**_PROPS, "title": "StatCardProps"}, None)
        comps = {c.name: c for c in load_components(tmp_path)}
        assert comps["StatCard"].contract is None


class TestBuildManifestContract:
    def test_version_stays_1_without_contracts(self, tmp_path: Path) -> None:
        _write_component(tmp_path, "StatCard", {**_PROPS, "title": "StatCardProps"}, None)
        manifest = build_manifest(load_components(tmp_path))
        assert manifest["version"] == 1
        assert "contract" not in manifest["components"]["StatCard"]

    def test_version_bumps_to_2_with_contract(self, tmp_path: Path) -> None:
        _write_component(tmp_path, "EntityList", _PROPS, _CONTRACT)
        _write_component(tmp_path, "StatCard", {**_PROPS, "title": "StatCardProps"}, None)
        manifest = build_manifest(load_components(tmp_path))
        assert manifest["version"] == 2
        # The contract-bearing component carries its operations...
        el = manifest["components"]["EntityList"]
        assert el["contract"]["operations"][0]["name"] == "list"
        # ...while the pure-UI component has no contract key.
        assert "contract" not in manifest["components"]["StatCard"]


class TestSubsetHardening:
    """Codex Phase-B findings: author-facing validation must fail loud, never
    crash with AttributeError/ValueError or silently accept out-of-subset shapes.
    """

    def _contract(self, output: dict) -> dict:
        return {
            "component": "X",
            "operations": [{"name": "get", "kind": "read", "input": {}, "output": output}],
        }

    def test_rejects_tuple_items(self) -> None:
        # array `items` as a LIST is tuple-validation — out of subset.
        bad = self._contract({"type": "array", "items": [{"type": "string"}]})
        with pytest.raises(GeneratorError, match="items"):
            validate_data_contract(load_data_contract_from_dict(bad))

    def test_rejects_non_dict_properties(self) -> None:
        bad = self._contract({"type": "object", "properties": []})
        with pytest.raises(GeneratorError, match="properties"):
            validate_data_contract(load_data_contract_from_dict(bad))

    def test_rejects_non_bool_additional_properties(self) -> None:
        bad = self._contract({"type": "object", "additionalProperties": {"type": "string"}})
        with pytest.raises(GeneratorError, match="additionalProperties"):
            validate_data_contract(load_data_contract_from_dict(bad))

    def test_rejects_non_dict_input(self) -> None:
        bad = {
            "component": "X",
            "operations": [{"name": "go", "kind": "write", "input": [["a", 1]], "output": {}}],
        }
        with pytest.raises(GeneratorError, match="input"):
            load_data_contract_from_dict(bad)

    def test_contract_component_must_match_filename(self, tmp_path: Path) -> None:
        # Sibling contract whose `component` disagrees with the props-derived
        # name must be rejected (guards against a mismatched/stale contract file).
        props = {**_PROPS, "title": "EntityListProps"}
        wrong = {**_CONTRACT, "component": "SomethingElse"}
        _write_component(tmp_path, "EntityList", props, wrong)
        with pytest.raises(GeneratorError, match="component"):
            load_components(tmp_path)


class TestContractlessManifestStability:
    def test_contractless_manifest_is_exactly_v1(self) -> None:
        # A contract-less component must emit a byte-stable v1 manifest entry
        # with NO contract key and the v1 $schema URL — proving the v2 bump is
        # strictly opt-in and old readers see no change.
        spec = CanvasComponentSpec(
            name="StatCard",
            props_schema={"title": "StatCardProps", "type": "object", "properties": {}},
            description="d",
        )
        assert build_manifest([spec]) == {
            "$schema": "https://forge.dev/schemas/canvas-manifest-v1.json",
            "version": 1,
            "components": {
                "StatCard": {
                    "description": "d",
                    "props_schema": {
                        "title": "StatCardProps",
                        "type": "object",
                        "properties": {},
                    },
                }
            },
        }


# A tiny helper used by the validation tests so they don't need tmp files.
def load_data_contract_from_dict(data: dict) -> DataContract:
    from forge.codegen.canvas_contract import data_contract_from_dict

    return data_contract_from_dict(data)

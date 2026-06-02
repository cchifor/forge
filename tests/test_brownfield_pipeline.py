"""Brownfield codegen step: emit the [contract_bindings] mapping artifact.

Gated on ``frontend.openapi_spec_url`` — a no-op (golden-safe) for greenfield
projects. When set, it writes the proposal for every selected contract-bearing
component, and re-validates a hand-edited file (fail loud).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.codegen.pipeline import _emit_contract_bindings
from forge.config import BackendConfig, FrontendConfig, FrontendFramework, ProjectConfig
from forge.errors import GeneratorError


def _contract_component_root(tmp: Path) -> Path:
    cc = tmp / "cc"
    cc.mkdir()
    (cc / "EntityList.props.schema.json").write_text(
        '{"title": "EntityListProps", "type": "object", "properties": {}}'
    )
    (cc / "EntityList.contract.json").write_text(
        json.dumps(
            {
                "component": "EntityList",
                "operations": [{"name": "list", "kind": "read", "input": {}, "output": {}}],
            }
        )
    )
    return cc


def _spec_file(tmp: Path) -> Path:
    spec = tmp / "spec.json"
    spec.write_text(json.dumps({"paths": {"/i": {"get": {"operationId": "listItems", "responses": {}}}}}))
    return spec


def _config(tmp: Path, *, with_spec: bool) -> ProjectConfig:
    opts = {"frontend.openapi_spec_url": str(_spec_file(tmp))} if with_spec else {}
    return ProjectConfig(
        project_name="App",
        backends=[BackendConfig(project_name="App")],
        frontend=FrontendConfig(framework=FrontendFramework.VUE, project_name="App"),
        components=["EntityList"],
        options=opts,
    )


def test_emits_bindings_artifact_when_spec_set(tmp_path: Path) -> None:
    cfg = _config(tmp_path, with_spec=True)
    proj = tmp_path / "proj"
    (proj / cfg.frontend_slug).mkdir(parents=True)
    _emit_contract_bindings(cfg, proj, None, components_root=_contract_component_root(tmp_path))
    out = proj / cfg.frontend_slug / "src" / "shared" / "api" / "contract-bindings.toml"
    assert out.is_file()
    text = out.read_text()
    assert "[contract_bindings.EntityList.list]" in text
    assert 'operation_id = "listItems"' in text


def test_noop_when_no_spec(tmp_path: Path) -> None:
    cfg = _config(tmp_path, with_spec=False)
    proj = tmp_path / "proj"
    (proj / cfg.frontend_slug).mkdir(parents=True)
    # No spec → greenfield → writes nothing, no crash.
    _emit_contract_bindings(cfg, proj, None, components_root=_contract_component_root(tmp_path))
    assert not (proj / cfg.frontend_slug / "src" / "shared" / "api" / "contract-bindings.toml").exists()


def test_hand_edited_invalid_binding_fails_loud(tmp_path: Path) -> None:
    cfg = _config(tmp_path, with_spec=True)
    proj = tmp_path / "proj"
    api = proj / cfg.frontend_slug / "src" / "shared" / "api"
    api.mkdir(parents=True)
    # A contract requiring an output field the binding doesn't satisfy.
    cc = tmp_path / "cc2"
    cc.mkdir()
    (cc / "EntityList.props.schema.json").write_text('{"title": "EntityListProps", "type": "object"}')
    (cc / "EntityList.contract.json").write_text(
        json.dumps({"component": "EntityList", "operations": [
            {"name": "list", "kind": "read", "input": {},
             "output": {"type": "object", "properties": {"x": {}}, "required": ["x"]}}]})
    )
    # Hand-edited file with no binding for `list`.
    (api / "contract-bindings.toml").write_text("[contract_bindings.EntityList]\n")
    with pytest.raises(GeneratorError) as exc:
        _emit_contract_bindings(cfg, proj, None, components_root=cc)
    assert exc.value.code == "FEATURE_CONTRACT_VIOLATION"

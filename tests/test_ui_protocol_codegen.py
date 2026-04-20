"""Tests for the UI-protocol schema codegen (1.1 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.codegen.ui_protocol import (
    DEFAULT_SCHEMA_ROOT,
    Schema,
    emit_all_for_default_root,
    emit_dart,
    emit_pydantic,
    emit_typescript,
    load_all,
    load_schema,
)
from forge.errors import GeneratorError


class TestLoadSchema:
    def test_loads_shipped_agent_state(self) -> None:
        schema = load_schema(DEFAULT_SCHEMA_ROOT / "agent_state.schema.json")
        assert schema.title == "AgentState"
        assert "cost" in schema.body["properties"]

    def test_rejects_missing_title(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.schema.json"
        path.write_text('{"type": "object", "properties": {}}')
        with pytest.raises(GeneratorError, match="title"):
            load_schema(path)

    def test_rejects_non_pascal_title(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.schema.json"
        path.write_text('{"title": "lower_case", "type": "object", "properties": {}}')
        with pytest.raises(GeneratorError, match="PascalCase"):
            load_schema(path)


class TestLoadAll:
    def test_discovers_every_shipped_schema(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        titles = {s.title for s in schemas}
        assert titles == {
            "AgUiPayload",
            "AgentState",
            "HitlResponse",
            "McpExtPayload",
            "ToolCallInfo",
            "UserPromptPayload",
            "WorkspaceActivity",
        }


class TestEmitTypescript:
    def test_emits_interface_per_schema(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_typescript(schemas)
        assert "export interface AgentState {" in out
        assert "export interface ToolCallInfo {" in out
        assert "export interface WorkspaceActivity {" in out

    def test_string_enum_becomes_literal_union(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_typescript(schemas)
        # ToolCallInfo.status is enum ["running", "completed", "error"]
        assert '"running" | "completed" | "error"' in out

    def test_additional_properties_becomes_index_signature(self) -> None:
        # AgentState has additionalProperties: true
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_typescript(schemas)
        assert "[key: string]: unknown;" in out

    def test_optional_fields_marked_with_question(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_typescript(schemas)
        # ToolCallInfo.args is optional
        assert "args?" in out


class TestEmitDart:
    def test_emits_class_per_schema(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_dart(schemas)
        assert "class AgentState {" in out
        assert "class ToolCallInfo {" in out

    def test_from_to_json_methods_present(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_dart(schemas)
        assert "factory ToolCallInfo.fromJson" in out
        assert "Map<String, dynamic> toJson()" in out

    def test_snake_to_camel_case_fields(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_dart(schemas)
        # UserPromptPayload.tool_call_id -> toolCallId in Dart
        assert "toolCallId" in out


class TestEmitPydantic:
    def test_emits_basemodel_per_schema(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_pydantic(schemas)
        assert "class AgentState(BaseModel):" in out
        assert "class ToolCallInfo(BaseModel):" in out

    def test_additional_properties_sets_extra_allow(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_pydantic(schemas)
        assert 'model_config = ConfigDict(extra="allow")' in out

    def test_enum_becomes_literal(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_pydantic(schemas)
        assert 'Literal["running", "completed", "error"]' in out

    def test_const_becomes_singleton_literal(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_pydantic(schemas)
        # AgUiPayload.engine is const 'ag-ui'
        assert 'Literal["ag-ui"]' in out
        assert 'Literal["mcp-ext"]' in out

    def test_optional_fields_have_default_none(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        out = emit_pydantic(schemas)
        assert "| None = None" in out


class TestEmitAll:
    def test_default_root_renders_all_targets(self) -> None:
        out = emit_all_for_default_root()
        assert set(out) == {"typescript", "dart", "pydantic"}
        for target, body in out.items():
            assert "AgentState" in body, f"{target} missing AgentState"
            assert "ToolCallInfo" in body, f"{target} missing ToolCallInfo"


class TestRoundtripInvariants:
    """Property tests: a simple schema should round-trip through every target consistently."""

    def test_every_schema_produces_non_empty_output(self) -> None:
        schemas = load_all(DEFAULT_SCHEMA_ROOT)
        assert len(schemas) >= 7
        ts = emit_typescript(schemas)
        dart = emit_dart(schemas)
        pyd = emit_pydantic(schemas)
        assert ts and dart and pyd

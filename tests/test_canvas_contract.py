"""Tests for the canvas component contract (1.2 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.codegen.canvas_contract import (
    CanvasComponentSpec,
    LintIssue,
    build_manifest,
    emit_manifest_json,
    lint_payload,
    load_components,
)
from forge.errors import GeneratorError


class TestLoadComponents:
    def test_loads_all_shipped_components(self) -> None:
        components = load_components()
        names = {c.name for c in components}
        assert names == {"CodeViewer", "DataTable", "DynamicForm", "Report", "WorkflowDiagram"}

    def test_rejects_title_without_props_suffix(self, tmp_path: Path) -> None:
        bad = tmp_path / "Bad.props.schema.json"
        bad.write_text('{"title": "Foo", "type": "object", "properties": {}}')
        with pytest.raises(GeneratorError, match="end with 'Props'"):
            load_components(tmp_path)


class TestBuildManifest:
    def test_manifest_has_entry_per_component(self) -> None:
        components = load_components()
        manifest = build_manifest(components)
        assert manifest["version"] == 1
        assert set(manifest["components"]) == {
            "CodeViewer",
            "DataTable",
            "DynamicForm",
            "Report",
            "WorkflowDiagram",
        }

    def test_manifest_includes_props_schema(self) -> None:
        components = load_components()
        manifest = build_manifest(components)
        dt = manifest["components"]["DataTable"]
        assert "props_schema" in dt
        assert "rows" in dt["props_schema"]["properties"]

    def test_emit_manifest_json_is_valid_json(self) -> None:
        import json

        out = emit_manifest_json()
        parsed = json.loads(out)
        assert parsed["version"] == 1


class TestLintPayload:
    def test_happy_path_report(self) -> None:
        payload = {
            "component_name": "Report",
            "props": {"markdown": "# hi"},
        }
        assert lint_payload(payload) == []

    def test_missing_required_prop(self) -> None:
        payload = {
            "component_name": "Report",
            "props": {"title": "oops"},
        }
        issues = lint_payload(payload)
        assert any(i.field == "markdown" and "missing" in i.message for i in issues)

    def test_unknown_component(self) -> None:
        payload = {
            "component_name": "DoesNotExist",
            "props": {},
        }
        issues = lint_payload(payload)
        assert issues and issues[0].component == "DoesNotExist"
        assert "not a registered" in issues[0].message

    def test_unknown_prop_rejected_when_additional_properties_false(self) -> None:
        payload = {
            "component_name": "Report",
            "props": {"markdown": "# hi", "mystery": "field"},
        }
        issues = lint_payload(payload)
        assert any(i.field == "mystery" and "unknown prop" in i.message for i in issues)

    def test_type_mismatch_surfaced(self) -> None:
        payload = {
            "component_name": "DataTable",
            "props": {
                "columns": "not an array",
                "rows": [],
            },
        }
        issues = lint_payload(payload)
        assert any(i.field == "columns" and "expected array" in i.message for i in issues)

    def test_enum_violation(self) -> None:
        payload = {
            "component_name": "WorkflowDiagram",
            "props": {
                "nodes": [{"id": "a", "label": "A", "status": "nonsense"}],
                "edges": [],
            },
        }
        # Top-level lint only checks immediate props; nested items are
        # beyond the shallow check. This test documents the current
        # shallow behavior — deeper checks land with full jsonschema
        # validation in Phase 2.
        issues = lint_payload(payload)
        # Shallow lint passes nested nodes through untouched.
        assert not any(i.field == "nodes" for i in issues)

    def test_lint_issue_str_is_readable(self) -> None:
        issue = LintIssue("DataTable", "rows", "expected array")
        assert str(issue) == "DataTable.rows: expected array"

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


# ---------------------------------------------------------------------------
# Lint edge cases (P2 follow-on — coverage backfill)
# ---------------------------------------------------------------------------


class TestLintPayloadEdgeCases:
    """Cover the early-return branches lint_payload takes when the
    payload's ``component_name`` or ``props`` are malformed."""

    def test_missing_component_name(self) -> None:
        issues = lint_payload({"props": {}})
        assert len(issues) == 1
        assert issues[0].component == "<unknown>"
        assert "component_name" in issues[0].field
        assert "missing or non-string" in issues[0].message

    def test_non_string_component_name(self) -> None:
        issues = lint_payload({"component_name": 42, "props": {}})
        assert len(issues) == 1
        assert issues[0].field == "component_name"

    def test_unknown_component_lists_known_options(self) -> None:
        issues = lint_payload({"component_name": "Nonexistent", "props": {}})
        assert len(issues) == 1
        assert "DataTable" in issues[0].message  # known options surfaced

    def test_missing_props_block(self) -> None:
        issues = lint_payload({"component_name": "DataTable"})
        assert any(
            i.field == "props" and "missing or non-object" in i.message
            for i in issues
        )

    def test_non_dict_props_block(self) -> None:
        issues = lint_payload({"component_name": "DataTable", "props": "string"})
        assert any(
            i.field == "props" and "missing or non-object" in i.message
            for i in issues
        )


class TestCheckTypeEveryBranch:
    """Each JSON Schema scalar/aggregate type has its own type-mismatch
    branch in ``_check_type``. Drive every one through ``lint_payload``."""

    def _component(self, name: str, ty: str) -> CanvasComponentSpec:
        # Build a minimal component declaring a single ``value`` prop of
        # the given JSON Schema type. Bypass the disk loader so the
        # tests don't depend on shipped components.
        schema = {
            "title": f"{name}Props",
            "type": "object",
            "properties": {"value": {"type": ty}},
            "required": ["value"],
            "additionalProperties": False,
        }
        return CanvasComponentSpec(name=name, props_schema=schema)

    def test_string_mismatch(self) -> None:
        comp = self._component("S", "string")
        issues = lint_payload(
            {"component_name": "S", "props": {"value": 42}},
            components=[comp],
        )
        assert any("expected string" in i.message for i in issues)

    def test_integer_mismatch_rejects_bool(self) -> None:
        comp = self._component("I", "integer")
        # bool is a subclass of int in Python; the validator must
        # explicitly reject it (an option set to True/False shouldn't
        # satisfy an integer field).
        issues = lint_payload(
            {"component_name": "I", "props": {"value": True}},
            components=[comp],
        )
        assert any("expected integer" in i.message for i in issues)

    def test_integer_mismatch_rejects_string(self) -> None:
        comp = self._component("I", "integer")
        issues = lint_payload(
            {"component_name": "I", "props": {"value": "1"}},
            components=[comp],
        )
        assert any("expected integer" in i.message for i in issues)

    def test_number_mismatch_rejects_bool(self) -> None:
        comp = self._component("N", "number")
        issues = lint_payload(
            {"component_name": "N", "props": {"value": True}},
            components=[comp],
        )
        assert any("expected number" in i.message for i in issues)

    def test_number_accepts_float_and_int(self) -> None:
        comp = self._component("N", "number")
        for v in (3.14, 7):
            issues = lint_payload(
                {"component_name": "N", "props": {"value": v}},
                components=[comp],
            )
            assert not any("expected number" in i.message for i in issues)

    def test_boolean_mismatch(self) -> None:
        comp = self._component("B", "boolean")
        issues = lint_payload(
            {"component_name": "B", "props": {"value": "true"}},
            components=[comp],
        )
        assert any("expected boolean" in i.message for i in issues)

    def test_object_mismatch(self) -> None:
        comp = self._component("O", "object")
        issues = lint_payload(
            {"component_name": "O", "props": {"value": []}},
            components=[comp],
        )
        assert any("expected object" in i.message for i in issues)

    def test_object_accepts_dict(self) -> None:
        comp = self._component("O", "object")
        issues = lint_payload(
            {"component_name": "O", "props": {"value": {"k": "v"}}},
            components=[comp],
        )
        assert not any("expected object" in i.message for i in issues)

    def test_enum_mismatch(self) -> None:
        # Build a component whose prop is a fixed enum.
        spec = CanvasComponentSpec(
            name="E",
            props_schema={
                "title": "EProps",
                "type": "object",
                "properties": {
                    "status": {"enum": ["active", "paused", "stopped"]}
                },
                "required": ["status"],
                "additionalProperties": False,
            },
        )
        issues = lint_payload(
            {"component_name": "E", "props": {"status": "running"}},
            components=[spec],
        )
        assert any("not in enum" in i.message for i in issues)

    def test_enum_accepts_listed_value(self) -> None:
        spec = CanvasComponentSpec(
            name="E",
            props_schema={
                "title": "EProps",
                "type": "object",
                "properties": {"status": {"enum": ["x", "y"]}},
                "required": ["status"],
                "additionalProperties": False,
            },
        )
        issues = lint_payload(
            {"component_name": "E", "props": {"status": "x"}},
            components=[spec],
        )
        assert issues == []


# ---------------------------------------------------------------------------
# CLI handler — `forge --canvas lint <payload.json>`
# ---------------------------------------------------------------------------


class TestCliLint:
    def test_clean_payload_exits_zero(self, tmp_path: Path, capsys) -> None:
        from forge.codegen.canvas_contract import cli_lint

        payload = {
            "component_name": "DataTable",
            "props": {"columns": [], "rows": []},
        }
        path = tmp_path / "payload.json"
        path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        rc = cli_lint(path)
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out
        assert "DataTable" in out

    def test_dirty_payload_exits_one_and_lists_issues(
        self, tmp_path: Path, capsys
    ) -> None:
        from forge.codegen.canvas_contract import cli_lint

        payload = {"component_name": "DataTable"}  # missing props
        path = tmp_path / "payload.json"
        path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        rc = cli_lint(path)
        assert rc == 1
        out = capsys.readouterr().out
        assert "lint issue" in out

    def test_unparseable_json_exits_two(
        self, tmp_path: Path, capsys
    ) -> None:
        from forge.codegen.canvas_contract import cli_lint

        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        rc = cli_lint(path)
        assert rc == 2
        out = capsys.readouterr().out
        assert "failed to parse" in out

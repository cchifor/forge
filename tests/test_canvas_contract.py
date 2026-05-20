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


# ---------------------------------------------------------------------------
# Canvas-package symmetry — the AG-UI client shims (Initiative #4)
# ---------------------------------------------------------------------------


class TestAgUiClientShipsAcrossPackages:
    """The AG-UI WebSocket client must be present and symmetric in every
    canvas package — Vue, Svelte, Dart.

    Initiative #4 ships TS shims for Vue + Svelte that mirror the
    existing Dart `AgUiClient`. The shims are intentionally tiny (a
    WebSocket wrapper that decodes frames and calls back) and must stay
    in sync: a future fix landing in one but not the other breaks the
    polyglot contract the same way the lint files would.
    """

    _REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_vue_shim_is_present(self) -> None:
        target = self._REPO_ROOT / "packages" / "canvas-vue" / "src" / "ag_ui_client.ts"
        assert target.is_file(), f"missing AgUiClient shim at {target}"

    def test_svelte_shim_is_present(self) -> None:
        target = self._REPO_ROOT / "packages" / "canvas-svelte" / "src" / "ag_ui_client.ts"
        assert target.is_file(), f"missing AgUiClient shim at {target}"

    def test_dart_client_still_present(self) -> None:
        # Initiative #4 must not regress the existing Dart client —
        # it's the canonical shape the TS shims mirror.
        target = (
            self._REPO_ROOT
            / "packages"
            / "forge-canvas-dart"
            / "lib"
            / "src"
            / "ag_ui_client.dart"
        )
        assert target.is_file()
        body = target.read_text(encoding="utf-8")
        # The Dart client expects `AgUiEvent.parse` (see line 24 of the file).
        # If we ever drop the import expectation, the generated parser
        # factory becomes load-bearing dead code.
        assert "parser: AgUiEvent.parse" in body

    def test_vue_and_svelte_shims_are_byte_equivalent_modulo_package_name(self) -> None:
        """The two TS shims must differ by exactly one line — the example
        import comment naming the package — to mirror the Dart/Vue/Svelte
        lint parity invariant. Drift in any other line means one package
        has a behaviour the other lacks.
        """
        vue = (
            self._REPO_ROOT / "packages" / "canvas-vue" / "src" / "ag_ui_client.ts"
        ).read_text(encoding="utf-8").splitlines()
        sv = (
            self._REPO_ROOT / "packages" / "canvas-svelte" / "src" / "ag_ui_client.ts"
        ).read_text(encoding="utf-8").splitlines()
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(vue, sv, strict=True)) if a != b]
        assert len(diff) == 1, (
            f"Vue/Svelte AgUiClient shims diverged on {len(diff)} lines — "
            "must differ by exactly the package-name import comment."
        )
        i, a, b = diff[0]
        assert "@forge/canvas-vue" in a and "@forge/canvas-svelte" in b, (
            f"line {i}: only the package-name comment may differ "
            f"(got vue={a!r}, svelte={b!r})"
        )

    def test_vue_shim_is_re_exported(self) -> None:
        body = (
            self._REPO_ROOT / "packages" / "canvas-vue" / "src" / "index.ts"
        ).read_text(encoding="utf-8")
        assert "export { AgUiClient }" in body
        assert "from './ag_ui_client'" in body

    def test_svelte_shim_is_re_exported(self) -> None:
        body = (
            self._REPO_ROOT / "packages" / "canvas-svelte" / "src" / "index.ts"
        ).read_text(encoding="utf-8")
        assert "export { AgUiClient }" in body
        assert "from './ag_ui_client'" in body


# ---------------------------------------------------------------------------
# Generated-props-only contract — Initiative #8
# ---------------------------------------------------------------------------


class TestGeneratedPropsOnly:
    """Initiative #8: generated prop types are the SINGLE source of truth.

    Every schema-driven canvas component (`CodeViewer`, `DataTable`,
    `DynamicForm`, `Report`, `WorkflowDiagram` — across Vue, Svelte,
    and Dart) must import its prop shape from the generated module
    rather than re-declaring it. Drift between hand-written and
    generated prop shapes was the load-bearing wart Initiative #8
    eliminates.

    These tests are deliberately grep-based:

        * stronger than "the generated file imports cleanly" (which a
          TS/Dart build catches anyway);
        * weaker than parsing the AST per language (which would require
          a TS / Dart toolchain inside the Python test runner).

    The pre-Initiative-#8 prop interfaces were named literally
    `Field`, `Column`, `Node`, `Edge` (TS/Svelte interface; Dart
    private class) — those names are what we grep for. The
    `interface Props` shape is allowed when it `extends` a generated
    interface (Svelte components do this to layer event-callback
    props on top of the schema-driven data props).
    """

    _REPO_ROOT = Path(__file__).resolve().parent.parent

    # File → (language, name of generated import). The list pins which
    # components participate in the contract — adding a new component
    # without a row here keeps the test silent (intentional: a new
    # component declares its own props schema and the codegen catches
    # the drift).
    _SCHEMA_DRIVEN_COMPONENTS: tuple[tuple[str, str], ...] = (
        ("packages/canvas-vue/src/components/CodeViewer.vue", "CodeViewerProps"),
        ("packages/canvas-vue/src/components/DataTable.vue", "DataTableProps"),
        ("packages/canvas-vue/src/components/DynamicForm.vue", "DynamicFormProps"),
        ("packages/canvas-vue/src/components/Report.vue", "ReportProps"),
        ("packages/canvas-vue/src/components/WorkflowDiagram.vue", "WorkflowDiagramProps"),
        ("packages/canvas-svelte/src/components/CodeViewer.svelte", "CodeViewerProps"),
        ("packages/canvas-svelte/src/components/DataTable.svelte", "DataTableProps"),
        ("packages/canvas-svelte/src/components/DynamicForm.svelte", "DynamicFormProps"),
        ("packages/canvas-svelte/src/components/Report.svelte", "ReportProps"),
        (
            "packages/canvas-svelte/src/components/WorkflowDiagram.svelte",
            "WorkflowDiagramProps",
        ),
    )

    # Dart components import the generated classes individually (not
    # via a barrel export) — pin the specific imports each one needs.
    _DART_COMPONENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "packages/forge-canvas-dart/lib/src/components/data_table.dart",
            ("DataTableColumn",),
        ),
        (
            "packages/forge-canvas-dart/lib/src/components/dynamic_form.dart",
            ("DynamicFormField",),
        ),
        (
            "packages/forge-canvas-dart/lib/src/components/workflow_diagram.dart",
            ("WorkflowDiagramNode", "WorkflowDiagramEdge"),
        ),
    )

    def test_every_ts_component_imports_generated_props(self) -> None:
        for rel, name in self._SCHEMA_DRIVEN_COMPONENTS:
            body = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "from '../generated/props'" in body, (
                f"{rel} does not import from '../generated/props' — "
                "every schema-driven canvas component must consume the "
                "generated prop type instead of re-declaring it."
            )
            assert name in body, (
                f"{rel} does not reference the generated `{name}` "
                "interface — the imported symbol must be the prop "
                "type for this component."
            )

    def test_every_dart_component_imports_generated_props(self) -> None:
        for rel, expected in self._DART_COMPONENTS:
            body = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "import '../generated/props.dart'" in body, (
                f"{rel} does not import the generated props library — "
                "every schema-driven canvas component must consume the "
                "generated sealed classes instead of declaring private "
                "mirror classes."
            )
            for sym in expected:
                assert sym in body, (
                    f"{rel} does not reference `{sym}` — "
                    "the imported sealed class must replace the old "
                    "private mirror class for this component."
                )

    def test_no_ts_component_redeclares_nested_prop_interface(self) -> None:
        # The pre-#8 components shipped local `Field`, `Column`, `Node`,
        # `Edge` interfaces that mirrored the schema by hand. After #8
        # those interfaces must be derived from the generated type
        # (`type X = GeneratedProps['x'][number]`), never declared via
        # `interface`.
        banned_decls = (
            "interface Field {",
            "interface Column {",
            "interface Node {",
            "interface Edge {",
        )
        for rel, _ in self._SCHEMA_DRIVEN_COMPONENTS:
            body = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
            for banned in banned_decls:
                assert banned not in body, (
                    f"{rel} re-declares `{banned.rstrip(' {')}` — "
                    "this interface lives in the generated props "
                    "module; pull it from there as "
                    "`type X = GeneratedProps['x'][number]`."
                )

    def test_no_dart_component_redeclares_private_mirror_class(self) -> None:
        # Pre-#8 Dart components shipped private mirror classes
        # (`_Column`, `_Field`, `_WfNode`, `_WfEdge`) with their own
        # `fromMap` factories — exactly the duplication the generated
        # sealed classes now subsume.
        banned_decls = (
            "class _Field {",
            "class _Column {",
            "class _WfNode {",
            "class _WfEdge {",
            "class _Node {",
            "class _Edge {",
        )
        for rel, _ in self._DART_COMPONENTS:
            body = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
            for banned in banned_decls:
                assert banned not in body, (
                    f"{rel} re-declares `{banned.rstrip(' {')}` — "
                    "this class lives in the generated props library; "
                    "use the matching sealed class instead."
                )

    def test_canvas_indexes_export_only_generated_props(self) -> None:
        # The Vue / Svelte index re-exports must point at
        # ``./generated/props`` — never at a hand-written sibling
        # module. The presence of any other origin path for a `Props`
        # type would silently double-declare the contract.
        for pkg, rel in (
            ("canvas-vue", "packages/canvas-vue/src/index.ts"),
            ("canvas-svelte", "packages/canvas-svelte/src/index.ts"),
        ):
            body = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "from './generated/props'" in body, (
                f"{pkg} index does not re-export from "
                "'./generated/props' — generated types are the "
                "single source of truth for the package's prop "
                "surface."
            )
            # No alternative prop-type origin permitted.
            for forbidden in (
                "from './props'",
                "from './props.ts'",
                "from './types'",
                "from './types.ts'",
            ):
                assert forbidden not in body, (
                    f"{pkg} index exports prop types from "
                    f"{forbidden!r} — must be the generated module."
                )

    def test_dart_library_exports_generated_props(self) -> None:
        rel = "packages/forge-canvas-dart/lib/forge_canvas.dart"
        body = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "export 'src/generated/props.dart';" in body, (
            "forge_canvas.dart must re-export the generated props "
            "library so downstream apps consume only the generated "
            "sealed classes."
        )

"""Unit tests for :class:`forge.reports.GenerationReport` shape + serialisation.

These tests pin the schema so a future bump of ``_report_version`` is
deliberate. The integration tests in ``test_cli_coverage.py`` (and the
``--update`` path's tests) cover wiring the report through the CLI;
this file covers the dataclass in isolation.
"""

from __future__ import annotations

import json

import pytest

from forge.reports import (
    REPORT_VERSION,
    FileInventoryEntry,
    GenerationReport,
    HiddenMutation,
    NextAction,
    SkippedToolchain,
    SyncPlanCandidate,
    SyncPlanReport,
)


class TestGenerationReportDefaults:
    def test_empty_report_serializes_to_dict(self) -> None:
        rep = GenerationReport()
        out = rep.to_dict()
        assert out["_report_version"] == REPORT_VERSION
        assert out["project_root"] == ""
        assert out["effective_config"] == {}
        assert out["option_origins"] == {}
        assert out["fragment_graph"] == {}
        assert out["file_inventory"] == []
        assert out["provenance_sidecar_paths"] == []
        assert out["warnings"] == []
        assert out["skipped_toolchains"] == []
        assert out["next_actions"] == []
        assert out["hidden_mutations"] == []
        # rollback_hint is omitted when empty.
        assert "rollback_hint" not in out

    def test_to_dict_is_json_serializable(self) -> None:
        rep = GenerationReport(project_root="/tmp/proj")
        # Should round-trip cleanly through json.
        text = json.dumps(rep.to_dict())
        loaded = json.loads(text)
        assert loaded["project_root"] == "/tmp/proj"

    def test_report_version_matches_module_constant(self) -> None:
        # The constant is the contract; a bump must be deliberate.
        assert REPORT_VERSION == 1
        rep = GenerationReport()
        assert rep._report_version == REPORT_VERSION


class TestGenerationReportPopulate:
    def test_full_report_round_trips(self) -> None:
        rep = GenerationReport(
            project_root="/tmp/proj",
            effective_config={"auth.mode": "none", "rag.backend": "qdrant"},
            option_origins={"auth.mode": "default", "rag.backend": "user"},
            fragment_graph={"rag_qdrant": [], "auth_keycloak": ["rag_qdrant"]},
            rollback_hint="rm -rf /tmp/proj",
        )
        rep.file_inventory.append(
            FileInventoryEntry(
                path="services/api/src/main.py",
                origin="base-template",
                sha256="a" * 64,
                template_name="services/python-service-template",
            )
        )
        rep.file_inventory.append(
            FileInventoryEntry(
                path="services/api/src/rag.py",
                origin="fragment",
                sha256="b" * 64,
                fragment_name="rag_qdrant",
            )
        )
        rep.provenance_sidecar_paths.append("forge.toml")
        rep.add_warning("plugin 'broken_one' failed to load")
        rep.add_skipped_toolchain(
            SkippedToolchain(
                backend="api",
                language="python",
                phase="verify",
                reason="--quiet suppressed verify",
            )
        )
        rep.add_next_action(
            NextAction(
                command="docker compose up",
                description="Start the generated stack",
                cwd=".",
            )
        )
        rep.add_hidden_mutation(
            HiddenMutation(
                path="auth.mode",
                previous="generate",
                current="none",
                reason="Keycloak disabled — gatekeeper cannot run",
            )
        )

        out = rep.to_dict()
        assert out["rollback_hint"] == "rm -rf /tmp/proj"
        assert out["fragment_graph"]["auth_keycloak"] == ["rag_qdrant"]
        assert out["option_origins"]["rag.backend"] == "user"
        assert out["option_origins"]["auth.mode"] == "default"
        assert len(out["file_inventory"]) == 2
        # base-template entry should carry template_name, not fragment_name.
        templ_entry = next(e for e in out["file_inventory"] if e["origin"] == "base-template")
        assert templ_entry["template_name"] == "services/python-service-template"
        assert "fragment_name" not in templ_entry
        # fragment entry should carry fragment_name.
        frag_entry = next(e for e in out["file_inventory"] if e["origin"] == "fragment")
        assert frag_entry["fragment_name"] == "rag_qdrant"
        assert out["warnings"] == ["plugin 'broken_one' failed to load"]
        assert out["skipped_toolchains"][0]["phase"] == "verify"
        assert out["next_actions"][0]["command"] == "docker compose up"
        assert out["hidden_mutations"][0]["path"] == "auth.mode"
        assert out["hidden_mutations"][0]["reason"].startswith("Keycloak disabled")
        # Whole payload must json-serialise.
        json.dumps(out)

    def test_add_warning_dedups(self) -> None:
        rep = GenerationReport()
        rep.add_warning("dup")
        rep.add_warning("dup")
        rep.add_warning("uniq")
        assert rep.warnings == ["dup", "uniq"]

    def test_add_hidden_mutation_dedups(self) -> None:
        rep = GenerationReport()
        rep.add_hidden_mutation(
            HiddenMutation(path="x", previous=1, current=2, reason="r")
        )
        # Same path + previous + current: dedup.
        rep.add_hidden_mutation(
            HiddenMutation(path="x", previous=1, current=2, reason="different reason")
        )
        # Different current: keep both.
        rep.add_hidden_mutation(
            HiddenMutation(path="x", previous=1, current=3, reason="r")
        )
        assert len(rep.hidden_mutations) == 2

    def test_add_next_action_dedups(self) -> None:
        rep = GenerationReport()
        rep.add_next_action(NextAction(command="a", description="d"))
        rep.add_next_action(NextAction(command="a", description="different"))
        rep.add_next_action(NextAction(command="a", description="d", cwd="services/api"))
        # First two collapse; the third has a different cwd so it survives.
        assert len(rep.next_actions) == 2

    def test_file_inventory_entry_drops_empty_optionals(self) -> None:
        entry = FileInventoryEntry(path="a/b", origin="user", sha256="x" * 64)
        out = entry.to_dict()
        assert out == {"path": "a/b", "origin": "user", "sha256": "x" * 64}
        assert "template_name" not in out
        assert "fragment_name" not in out


class TestSyncPlanReport:
    def test_empty_totals_are_all_zero(self) -> None:
        rep = SyncPlanReport()
        assert rep.totals() == {
            "safe-apply": 0,
            "needs-review": 0,
            "skipped-vacuous": 0,
            "conflict": 0,
        }

    def test_candidates_aggregate_into_totals(self) -> None:
        rep = SyncPlanReport(project_root="/tmp/proj")
        rep.add_candidate(
            SyncPlanCandidate(
                candidate_id="rag_qdrant::services/api/rag.py",
                kind="file",
                disposition="safe-apply",
                path="services/api/rag.py",
                fragment_name="rag_qdrant",
            )
        )
        rep.add_candidate(
            SyncPlanCandidate(
                candidate_id="rag_qdrant::middleware",
                kind="block",
                disposition="needs-review",
                rationale="fragment template snippet drifted",
            )
        )
        out = rep.to_dict()
        assert out["totals"]["safe-apply"] == 1
        assert out["totals"]["needs-review"] == 1
        assert out["totals"]["conflict"] == 0
        assert len(out["candidates"]) == 2
        assert out["candidates"][0]["path"] == "services/api/rag.py"
        # JSON round-trip ok.
        json.dumps(out)

    def test_warnings_dedup(self) -> None:
        rep = SyncPlanReport()
        rep.add_warning("missing fragment")
        rep.add_warning("missing fragment")
        assert rep.warnings == ["missing fragment"]


@pytest.mark.parametrize(
    "report_cls",
    [GenerationReport, SyncPlanReport],
)
def test_default_report_version_is_one(report_cls):
    """Every report dataclass starts at version 1."""
    rep = report_cls()
    assert rep._report_version == 1

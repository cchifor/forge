"""Unit tests for :class:`forge.reports.UpdateReport`.

Covers the dataclass shape, serialisation, and per-file disposition
helpers. Integration tests that walk the full ``forge --update --json``
path live in ``tests/test_cli_coverage.py``.
"""

from __future__ import annotations

import json

import pytest

from forge.reports import (
    REPORT_VERSION,
    FileDisposition,
    HiddenMutation,
    NextAction,
    UpdateFileEntry,
    UpdateReport,
)


class TestUpdateReportDefaults:
    def test_empty_report_serialises(self) -> None:
        rep = UpdateReport()
        out = rep.to_dict()
        assert out["_report_version"] == REPORT_VERSION
        assert out["project_root"] == ""
        assert out["file_dispositions"] == []
        assert out["legacy_summary"] == {}
        # update_mode + rollback_hint are optional.
        assert "update_mode" not in out
        assert "rollback_hint" not in out

    def test_round_trip_through_json(self) -> None:
        rep = UpdateReport(project_root="/tmp/proj", update_mode="merge")
        json.dumps(rep.to_dict())


class TestUpdateReportPopulate:
    def test_full_report_round_trips(self) -> None:
        rep = UpdateReport(
            project_root="/tmp/proj",
            effective_config={"auth.mode": "generate"},
            option_origins={"auth.mode": "user"},
            fragment_graph={"auth_keycloak": []},
            update_mode="merge",
            rollback_hint="git restore -SW .",
        )
        rep.add_file(
            UpdateFileEntry(
                path="services/api/src/main.py",
                disposition="unchanged",
            )
        )
        rep.add_file(
            UpdateFileEntry(
                path="services/api/src/auth.py",
                disposition="merged",
                fragment_name="auth_keycloak",
            )
        )
        rep.add_file(
            UpdateFileEntry(
                path="services/api/src/conflict.py",
                disposition="sidecar-emitted",
                fragment_name="auth_keycloak",
                sidecar_path="services/api/src/conflict.py.forge-merge",
            )
        )
        rep.add_warning("template version drift detected")
        rep.add_next_action(
            NextAction(
                command="git diff",
                description="Review applied changes",
            )
        )
        rep.hidden_mutations.append(
            HiddenMutation(
                path="auth.mode",
                previous="generate",
                current="none",
                reason="Keycloak disabled in this run",
            )
        )
        rep.legacy_summary = {
            "fragments_applied": ["auth_keycloak"],
            "file_conflicts": 1,
            "forge_version_before": "1.2.0",
            "forge_version_after": "1.2.1",
        }

        out = rep.to_dict()
        assert out["update_mode"] == "merge"
        assert out["rollback_hint"] == "git restore -SW ."
        assert len(out["file_dispositions"]) == 3
        dispositions = {e["disposition"] for e in out["file_dispositions"]}
        assert dispositions == {"unchanged", "merged", "sidecar-emitted"}
        # sidecar entry carries sidecar_path.
        sc = next(
            e for e in out["file_dispositions"] if e["disposition"] == "sidecar-emitted"
        )
        assert sc["sidecar_path"] == "services/api/src/conflict.py.forge-merge"
        # unchanged entry drops the optional fields.
        unchanged = next(
            e for e in out["file_dispositions"] if e["disposition"] == "unchanged"
        )
        assert "fragment_name" not in unchanged
        assert "sidecar_path" not in unchanged
        assert out["legacy_summary"]["file_conflicts"] == 1
        assert out["warnings"] == ["template version drift detected"]
        json.dumps(out)

    def test_add_warning_dedups(self) -> None:
        rep = UpdateReport()
        rep.add_warning("dup")
        rep.add_warning("dup")
        assert rep.warnings == ["dup"]

    def test_add_next_action_dedups(self) -> None:
        rep = UpdateReport()
        rep.add_next_action(NextAction(command="x", description="d"))
        rep.add_next_action(NextAction(command="x", description="d"))
        assert len(rep.next_actions) == 1


@pytest.mark.parametrize(
    "disposition",
    [
        "unchanged",
        "modified",
        "merged",
        "conflict",
        "sidecar-emitted",
        "user-modified-skipped",
    ],
)
def test_every_file_disposition_serialises(disposition: FileDisposition) -> None:
    """Every value in the :data:`FileDisposition` Literal union round-trips."""
    entry = UpdateFileEntry(path="x", disposition=disposition)
    out = entry.to_dict()
    assert out["disposition"] == disposition

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


class TestRunUpdateJsonEnvelope:
    """End-to-end: ``forge --update --json`` emits the new ``report`` key
    alongside the pre-existing summary keys.

    Mocks ``update_project`` so no on-disk project is required — the
    test exercises the CLI shape, not the underlying updater
    semantics."""

    def test_envelope_carries_report_and_legacy_keys(self, tmp_path, capsys) -> None:
        from argparse import Namespace
        from unittest.mock import patch

        from forge.cli.commands.update import _run_update

        fake_summary: dict = {
            "backends": ["api"],
            "fragments_applied": ["rag_qdrant"],
            "forge_version_before": "1.2.0",
            "forge_version_after": "1.2.1",
            "classification": {
                "services/api/src/main.py": "unchanged",
                "services/api/src/rag.py": "user-modified",
                "services/api/src/orders.py": "missing",
            },
            "user_modified_count": 1,
            "uninstalled": [],
            "update_mode": "merge",
            "file_conflicts": 0,
            "template_updates": [],
        }

        args = Namespace(
            project_path=str(tmp_path),
            quiet=False,
            update_mode="merge",
            no_template_update=False,
            json_output=True,
        )

        with patch(
            "forge.sync.forge_to_project.updater.update_project",
            return_value=fake_summary,
        ), pytest.raises(SystemExit) as exc:
            _run_update(args)
        assert exc.value.code == 0

        out = capsys.readouterr().out
        # The CLI emits a one-line "forge update: ..." prelude on stdout
        # before the JSON payload; strip it.
        envelope = json.loads(out.split("\n", 1)[1])

        # Legacy keys remain.
        assert envelope["fragments_applied"] == ["rag_qdrant"]
        assert envelope["forge_version_after"] == "1.2.1"
        assert envelope["file_conflicts"] == 0
        # New ``report`` key is present and self-consistent.
        report = envelope["report"]
        assert report["_report_version"] == 1
        assert report["update_mode"] == "merge"
        assert report["project_root"] == str(tmp_path)
        # Per-file dispositions reflect classification.
        dispositions = {e["path"]: e["disposition"] for e in report["file_dispositions"]}
        assert dispositions["services/api/src/main.py"] == "unchanged"
        assert dispositions["services/api/src/rag.py"] == "user-modified-skipped"
        # 'missing' maps to 'modified' so the agent knows the file was touched.
        assert dispositions["services/api/src/orders.py"] == "modified"
        # legacy_summary holds the full pre-#5 dict verbatim.
        assert report["legacy_summary"]["fragments_applied"] == ["rag_qdrant"]

    def test_envelope_surfaces_conflict_warning(self, tmp_path, capsys) -> None:
        from argparse import Namespace
        from unittest.mock import patch

        from forge.cli.commands.update import _run_update

        fake_summary: dict = {
            "backends": ["api"],
            "fragments_applied": [],
            "forge_version_before": "1.2.0",
            "forge_version_after": "1.2.0",
            "classification": {},
            "user_modified_count": 0,
            "uninstalled": [],
            "update_mode": "merge",
            "file_conflicts": 3,
            "template_updates": [
                {
                    "language": "python",
                    "status": "conflict",
                    "project_version": "1.0.0",
                    "current_version": "1.1.0",
                }
            ],
        }
        args = Namespace(
            project_path=str(tmp_path),
            quiet=False,
            update_mode="merge",
            no_template_update=False,
            json_output=True,
        )
        with patch(
            "forge.sync.forge_to_project.updater.update_project",
            return_value=fake_summary,
        ), pytest.raises(SystemExit) as exc:
            _run_update(args)
        assert exc.value.code == 0
        out = capsys.readouterr().out
        envelope = json.loads(out.split("\n", 1)[1])
        warnings = envelope["report"]["warnings"]
        assert any("3 merge conflict" in w for w in warnings)
        assert any("template python update conflict" in w for w in warnings)

"""Tests for ``forge --verify`` (Phase 2, bidirectional sync).

Covers the read-only drift detection verb end-to-end:

* core ``verify_project()`` algorithm — happy / drift / conflict paths.
* per-record status classification across the file + block axes.
* ``scope`` filter on the report contents.
* ``fail_on`` threshold mapped through the CLI exit-code helper.
* JSON / human render shapes.
* CLI dispatch wiring (``--verify``, ``--verify-scope``, ``--fail-on``).
"""

from __future__ import annotations

import io
import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.cli.commands.verify import _run_verify, _verify_exit_code
from forge.errors import EXIT_VERIFY_CONFLICT, EXIT_VERIFY_DRIFT
from forge.fragments import MARKER_PREFIX
from forge.sync.manifest import write_forge_toml
from forge.sync.merge import MergeBlockCollector, sha256_of_text
from forge.sync.project_to_forge.verify import (
    BlockVerifyEntry,
    FileVerifyEntry,
    VerifyReport,
    verify_project,
)
from forge.sync.provenance import sha256_of

# ---------------------------------------------------------------------------
# Test fixtures — small helpers to build a minimal forge-tracked project tree
# without going through the full generator.
# ---------------------------------------------------------------------------


def _block_text(feature_key: str, marker_bare: str, body: str) -> str:
    """Render a sentinel-wrapped block matching what the injector emits."""
    return (
        f"# {MARKER_PREFIX}BEGIN {feature_key}:{marker_bare}\n"
        f"{body}"
        f"# {MARKER_PREFIX}END {feature_key}:{marker_bare}\n"
    )


def _write_minimal_project(tmp_path: Path, *, with_block: bool = False) -> dict:
    """Scaffold a project with one tracked file (and optionally one block).

    Returns the SHA / key metadata callers need to assert against.
    """
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    main_py = src / "main.py"
    block_segment = ""
    block_key = ""
    block_sha = ""
    if with_block:
        body = "# block body line 1\n# block body line 2\n"
        block_segment = _block_text("middleware_cors", "MIDDLEWARE_REGISTRATION", body)
        block_sha = sha256_of_text(body)
        block_key = MergeBlockCollector.key_for(
            "src/app/main.py", "middleware_cors", "MIDDLEWARE_REGISTRATION"
        )
    main_py.write_text(f"# top of file\n{block_segment}# bottom of file\n")
    main_sha = sha256_of(main_py)

    provenance = {
        "src/app/main.py": {
            "origin": "base-template",
            "sha256": main_sha,
            "template_name": "python-service-template",
            "template_version": "0.6.1",
        }
    }
    merge_blocks: dict[str, dict[str, str]] = {}
    if with_block:
        merge_blocks[block_key] = {
            "sha256": block_sha,
            "fragment_name": "middleware_cors",
            "fragment_version": "1.2.0",
        }

    write_forge_toml(
        tmp_path / "forge.toml",
        version="1.0.0",
        project_name="demo",
        templates={"python": "services/python-service-template"},
        options={},
        provenance=provenance,
        merge_blocks=merge_blocks if merge_blocks else None,
    )
    return {
        "main_sha": main_sha,
        "block_key": block_key,
        "block_sha": block_sha,
        "main_py": main_py,
    }


# ---------------------------------------------------------------------------
# verify_project — happy path
# ---------------------------------------------------------------------------


class TestVerifyClean:
    """Fresh project, no edits — worst='clean', exit 0 under default fail_on."""

    def test_clean_files_only(self, tmp_path: Path) -> None:
        _write_minimal_project(tmp_path)
        report = verify_project(tmp_path)
        assert report.worst == "clean"
        assert report.summary["unchanged"] == 1
        assert report.summary["user-modified"] == 0
        assert report.summary["missing"] == 0
        assert report.summary["sentinel-corrupt"] == 0
        assert len(report.records) == 1
        assert report.records[0].status == "unchanged"
        assert _verify_exit_code(report, "drift") == 0

    def test_clean_with_block(self, tmp_path: Path) -> None:
        _write_minimal_project(tmp_path, with_block=True)
        report = verify_project(tmp_path)
        assert report.worst == "clean"
        # File provenance counts as 1; block counts as 1; both unchanged.
        assert report.summary["unchanged"] == 2
        # ...but the file's SHA changed (block content is part of the file)
        # — wait, this case has the block at write time, so the recorded
        # file SHA includes the block. Re-confirming both are unchanged.
        assert len(report.records) == 1
        assert len(report.merge_blocks) == 1
        assert report.merge_blocks[0].status == "unchanged"


# ---------------------------------------------------------------------------
# verify_project — file-level drift
# ---------------------------------------------------------------------------


class TestVerifyFileDrift:
    def test_user_modified_file_status(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path)
        meta["main_py"].write_text("# user edited the whole thing\n")
        report = verify_project(tmp_path)
        assert report.worst == "drift"
        assert report.summary["user-modified"] == 1
        assert report.summary["unchanged"] == 0
        (rec,) = report.records
        assert rec.status == "user-modified"
        # current_sha is the post-edit digest; baseline is the original.
        assert rec.current_sha is not None
        assert rec.current_sha != rec.baseline_sha
        assert _verify_exit_code(report, "drift") == EXIT_VERIFY_DRIFT

    def test_missing_file_status(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path)
        meta["main_py"].unlink()
        report = verify_project(tmp_path)
        assert report.worst == "drift"
        assert report.summary["missing"] == 1
        (rec,) = report.records
        assert rec.status == "missing"
        assert rec.current_sha is None
        # Baseline is still present so the operator can see what was expected.
        assert rec.baseline_sha == meta["main_sha"]
        assert _verify_exit_code(report, "drift") == EXIT_VERIFY_DRIFT


# ---------------------------------------------------------------------------
# verify_project — block-level drift + conflict
# ---------------------------------------------------------------------------


class TestVerifyBlockDrift:
    def test_block_user_modified(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path, with_block=True)
        # Edit the body between the sentinels — sentinels intact, body diff.
        # We also need to re-stamp the file sha so the file row stays clean,
        # otherwise we'd be testing two drifts at once.
        original_text = meta["main_py"].read_text()
        modified_block_segment = _block_text(
            "middleware_cors", "MIDDLEWARE_REGISTRATION", "# user wrote here\n"
        )
        edited_text = original_text.replace(
            _block_text(
                "middleware_cors",
                "MIDDLEWARE_REGISTRATION",
                "# block body line 1\n# block body line 2\n",
            ),
            modified_block_segment,
        )
        meta["main_py"].write_text(edited_text)
        # File SHA also changed — re-stamp the manifest entry to isolate the
        # block-drift case from the file-drift case.
        new_file_sha = sha256_of(meta["main_py"])
        manifest = tmp_path / "forge.toml"
        body = manifest.read_text()
        body = body.replace(meta["main_sha"], new_file_sha)
        manifest.write_text(body)

        report = verify_project(tmp_path)
        assert report.worst == "drift"
        assert report.summary["unchanged"] == 1  # the file row
        assert report.summary["user-modified"] == 1  # the block row
        (blk,) = report.merge_blocks
        assert blk.status == "user-modified"
        assert blk.feature_key == "middleware_cors"
        assert blk.marker == "FORGE:MIDDLEWARE_REGISTRATION"
        assert blk.current_sha is not None
        assert blk.current_sha != blk.baseline_sha

    def test_sentinel_corrupt_is_conflict(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path, with_block=True)
        # Garble the BEGIN sentinel so _read_block_body returns None.
        text = meta["main_py"].read_text()
        text = text.replace(f"{MARKER_PREFIX}BEGIN", "OOPS_GARBAGE")
        meta["main_py"].write_text(text)
        # Re-stamp the file SHA so only the block row drifts.
        new_file_sha = sha256_of(meta["main_py"])
        manifest = tmp_path / "forge.toml"
        body = manifest.read_text()
        body = body.replace(meta["main_sha"], new_file_sha)
        manifest.write_text(body)

        report = verify_project(tmp_path)
        assert report.worst == "conflict"
        assert report.summary["sentinel-corrupt"] == 1
        (blk,) = report.merge_blocks
        assert blk.status == "sentinel-corrupt"
        assert blk.current_sha is None
        assert _verify_exit_code(report, "drift") == EXIT_VERIFY_CONFLICT


# ---------------------------------------------------------------------------
# Scope filter
# ---------------------------------------------------------------------------


class TestScopeFilter:
    def test_scope_files_skips_blocks(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path, with_block=True)
        # Corrupt the block sentinel — this would be conflict at scope=all,
        # but at scope=files the block walk is skipped entirely.
        text = meta["main_py"].read_text()
        text = text.replace(f"{MARKER_PREFIX}BEGIN", "OOPS_GARBAGE")
        meta["main_py"].write_text(text)
        # Re-stamp file sha so file row is unchanged.
        new_file_sha = sha256_of(meta["main_py"])
        manifest = tmp_path / "forge.toml"
        body = manifest.read_text()
        body = body.replace(meta["main_sha"], new_file_sha)
        manifest.write_text(body)

        report = verify_project(tmp_path, scope="files")
        assert report.worst == "clean"
        assert report.merge_blocks == []
        assert len(report.records) == 1

    def test_scope_blocks_skips_files(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path, with_block=True)
        # Delete the tracked file — that's "missing" at scope=all but skipped
        # entirely at scope=blocks. (The block walk will hit "missing" too
        # because the file is gone — but we want to confirm scope=blocks
        # ALSO returns no file rows.)
        # Actually, deleting affects block path too. Use a fresh project
        # without the block, modify file, scope=blocks should be clean.
        meta["main_py"].write_text("# user edited\n")

        report = verify_project(tmp_path, scope="blocks")
        # File row is skipped; block row still walked. The block on disk
        # was lost when the file was rewritten — sentinels gone.
        assert report.records == []
        assert len(report.merge_blocks) == 1
        # The block target file still exists but the sentinels are gone
        # → _read_block_body returns None → sentinel-corrupt.
        assert report.merge_blocks[0].status == "sentinel-corrupt"

    def test_scope_fragments_walks_both(self, tmp_path: Path) -> None:
        """scope='fragments' currently treated as 'all' (Phase 4 will filter)."""
        _write_minimal_project(tmp_path, with_block=True)
        report = verify_project(tmp_path, scope="fragments")
        assert len(report.records) == 1
        assert len(report.merge_blocks) == 1


# ---------------------------------------------------------------------------
# fail_on threshold (verified through the CLI helper, which is pure)
# ---------------------------------------------------------------------------


class TestFailOnThreshold:
    def _report(self, worst: str) -> VerifyReport:
        # Build a stub with just the worst field — _verify_exit_code only
        # reads that.
        summary = {"unchanged": 0, "user-modified": 0, "missing": 0, "sentinel-corrupt": 0}
        return VerifyReport(worst=worst, summary=summary)  # type: ignore[arg-type]

    def test_never_always_passes(self) -> None:
        assert _verify_exit_code(self._report("clean"), "never") == 0
        assert _verify_exit_code(self._report("drift"), "never") == 0
        assert _verify_exit_code(self._report("conflict"), "never") == 0

    def test_drift_threshold_drift_fails(self) -> None:
        assert _verify_exit_code(self._report("clean"), "drift") == 0
        assert _verify_exit_code(self._report("drift"), "drift") == EXIT_VERIFY_DRIFT
        assert _verify_exit_code(self._report("conflict"), "drift") == EXIT_VERIFY_CONFLICT

    def test_conflict_threshold_drift_passes(self) -> None:
        assert _verify_exit_code(self._report("clean"), "conflict") == 0
        assert _verify_exit_code(self._report("drift"), "conflict") == 0
        assert _verify_exit_code(self._report("conflict"), "conflict") == EXIT_VERIFY_CONFLICT


# ---------------------------------------------------------------------------
# Missing forge.toml — exit 5 + structured error
# ---------------------------------------------------------------------------


class TestMissingForgeToml:
    def test_verify_project_raises(self, tmp_path: Path) -> None:
        # No forge.toml at all in tmp_path.
        with pytest.raises(FileNotFoundError):
            verify_project(tmp_path)

    def test_cli_dispatch_returns_exit_5_text(self, tmp_path: Path, capsys) -> None:
        # No forge.toml; CLI should write a human error and return 5.
        ns = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=False,
        )
        rc = _run_verify(ns)
        assert rc == 5
        err = capsys.readouterr().err
        assert "no forge.toml" in err

    def test_cli_dispatch_returns_exit_5_json(self, tmp_path: Path, capsys) -> None:
        ns = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=True,
        )
        rc = _run_verify(ns)
        assert rc == 5
        out = capsys.readouterr().out
        envelope = json.loads(out.strip())
        assert "error" in envelope
        assert "no forge.toml" in envelope["error"]


# ---------------------------------------------------------------------------
# JSON shape contract
# ---------------------------------------------------------------------------


class TestJsonShape:
    def test_clean_envelope_shape(self, tmp_path: Path) -> None:
        _write_minimal_project(tmp_path)
        report = verify_project(tmp_path)
        payload = report.to_dict()
        # Required top-level keys.
        assert set(payload) == {"worst", "summary", "records", "merge_blocks"}
        assert payload["worst"] == "clean"
        # Summary always has all four canonical buckets.
        assert set(payload["summary"]) == {
            "unchanged",
            "user-modified",
            "missing",
            "sentinel-corrupt",
        }
        # Records shape.
        (rec,) = payload["records"]
        assert rec["rel_path"] == "src/app/main.py"
        assert rec["origin"] == "base-template"
        assert rec["status"] == "unchanged"
        assert rec["template_name"] == "python-service-template"
        assert rec["template_version"] == "0.6.1"
        assert "baseline_sha" in rec
        assert "current_sha" in rec

    def test_drift_envelope_shape(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path)
        meta["main_py"].write_text("# edit\n")
        report = verify_project(tmp_path)
        payload = report.to_dict()
        assert payload["worst"] == "drift"
        (rec,) = payload["records"]
        assert rec["status"] == "user-modified"

    def test_block_envelope_shape(self, tmp_path: Path) -> None:
        _write_minimal_project(tmp_path, with_block=True)
        report = verify_project(tmp_path)
        payload = report.to_dict()
        (blk,) = payload["merge_blocks"]
        assert blk["key"]
        assert blk["rel_path"] == "src/app/main.py"
        assert blk["feature_key"] == "middleware_cors"
        assert blk["marker"] == "FORGE:MIDDLEWARE_REGISTRATION"
        assert blk["status"] == "unchanged"
        assert blk["fragment_name"] == "middleware_cors"
        assert blk["fragment_version"] == "1.2.0"


# ---------------------------------------------------------------------------
# Human render — exercise the format paths
# ---------------------------------------------------------------------------


class TestHumanRender:
    def test_clean_renders_summary(self, tmp_path: Path) -> None:
        _write_minimal_project(tmp_path, with_block=True)
        report = verify_project(tmp_path)
        buf = io.StringIO()
        report.render_human(buf)
        out = buf.getvalue()
        assert "forge verify: clean" in out
        assert "1 files" in out
        assert "1 blocks" in out

    def test_drift_renders_per_record_lines(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path)
        meta["main_py"].write_text("# edited\n")
        report = verify_project(tmp_path)
        buf = io.StringIO()
        report.render_human(buf)
        out = buf.getvalue()
        assert "forge verify: drift" in out
        assert "src/app/main.py" in out
        assert "python-service-template" in out
        assert "0.6.1" in out

    def test_conflict_renders_zero_drift_lines(self, tmp_path: Path) -> None:
        meta = _write_minimal_project(tmp_path, with_block=True)
        # Garble sentinel; re-stamp file SHA so only block row trips.
        text = meta["main_py"].read_text()
        text = text.replace(f"{MARKER_PREFIX}BEGIN", "OOPS")
        meta["main_py"].write_text(text)
        new_file_sha = sha256_of(meta["main_py"])
        manifest = tmp_path / "forge.toml"
        manifest.write_text(manifest.read_text().replace(meta["main_sha"], new_file_sha))

        report = verify_project(tmp_path)
        buf = io.StringIO()
        report.render_human(buf)
        out = buf.getvalue()
        assert "drift on 0 files, 1 conflicts" in out
        assert "(block)" in out

    def test_sample_cap_caps_at_twenty(self, tmp_path: Path) -> None:
        # Scaffold 25 tracked files, edit all 25 — render should cap at 20.
        provenance: dict[str, dict[str, str]] = {}
        for i in range(25):
            f = tmp_path / f"file_{i:02d}.py"
            f.write_text(f"# file {i}\n")
            sha = sha256_of(f)
            provenance[f.name] = {"origin": "base-template", "sha256": sha}
        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0",
            project_name="bulk",
            templates={"python": "p"},
            options={},
            provenance=provenance,
        )
        # Drift every file.
        for i in range(25):
            (tmp_path / f"file_{i:02d}.py").write_text(f"# file {i} edited\n")

        report = verify_project(tmp_path)
        buf = io.StringIO()
        report.render_human(buf)
        out = buf.getvalue()
        # 20 sample lines + the "... and N more" overflow line.
        assert "and 5 more" in out


# ---------------------------------------------------------------------------
# CLI dispatch — _run_verify with a real on-disk project
# ---------------------------------------------------------------------------


class TestRunVerifyDispatch:
    def test_clean_project_returns_zero(self, tmp_path: Path, capsys) -> None:
        _write_minimal_project(tmp_path)
        ns = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=False,
        )
        rc = _run_verify(ns)
        assert rc == 0
        out = capsys.readouterr().out
        assert "clean" in out

    def test_drift_project_returns_ten(self, tmp_path: Path, capsys) -> None:
        meta = _write_minimal_project(tmp_path)
        meta["main_py"].write_text("# edited\n")
        ns = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=False,
        )
        rc = _run_verify(ns)
        assert rc == EXIT_VERIFY_DRIFT
        out = capsys.readouterr().out
        assert "drift" in out

    def test_fail_on_never_returns_zero_even_with_drift(self, tmp_path: Path, capsys) -> None:
        meta = _write_minimal_project(tmp_path)
        meta["main_py"].write_text("# edited\n")
        ns = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="never",
            json_output=False,
        )
        rc = _run_verify(ns)
        assert rc == 0

    def test_json_output_emits_valid_json(self, tmp_path: Path, capsys) -> None:
        _write_minimal_project(tmp_path)
        ns = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=True,
        )
        rc = _run_verify(ns)
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["worst"] == "clean"


# ---------------------------------------------------------------------------
# Manifest-edge cases — malformed merge_block keys
# ---------------------------------------------------------------------------


class TestManifestEdges:
    def test_malformed_block_key_surfaces_as_conflict(self, tmp_path: Path) -> None:
        """A hand-edited or pre-1.0.0a3 key without '::' surfaces as conflict."""
        # Hand-write a forge.toml with a bogus merge_block key.
        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.0.0",
            project_name="weird",
            templates={"python": "p"},
            options={},
            merge_blocks={"not-a-canonical-key": {"sha256": "deadbeef"}},
        )
        report = verify_project(tmp_path)
        assert report.worst == "conflict"
        (blk,) = report.merge_blocks
        assert blk.status == "sentinel-corrupt"
        assert blk.key == "not-a-canonical-key"

    def test_v1_provenance_entry_minimal_fields(self, tmp_path: Path) -> None:
        """A v1 entry (just origin+sha) classifies cleanly without version fields."""
        f = tmp_path / "legacy.py"
        f.write_text("# old\n")
        sha = sha256_of(f)
        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0",
            project_name="v1",
            templates={"python": "p"},
            options={},
            provenance={"legacy.py": {"origin": "base-template", "sha256": sha}},
        )
        report = verify_project(tmp_path)
        assert report.worst == "clean"
        (rec,) = report.records
        assert rec.template_name is None
        assert rec.template_version is None


# ---------------------------------------------------------------------------
# CLI flag end-to-end (extends what tests/test_cli_flags.py covers)
# ---------------------------------------------------------------------------


class TestVerifyCliFlags:
    """End-to-end argparse → dispatch wiring for ``forge --verify``."""

    def _capture_argv(self, *argv: str) -> Namespace:
        with patch.object(sys, "argv", ["forge", *argv]):
            from forge.cli.parser import _parse_args  # noqa: PLC0415

            return _parse_args()

    def test_verify_alone(self) -> None:
        args = self._capture_argv("--verify")
        assert args.verify is True
        assert args.verify_scope == "all"
        assert args.verify_fail_on == "drift"

    def test_verify_scope_propagates(self) -> None:
        args = self._capture_argv("--verify", "--verify-scope", "files")
        assert args.verify_scope == "files"

    def test_verify_scope_blocks(self) -> None:
        args = self._capture_argv("--verify", "--verify-scope", "blocks")
        assert args.verify_scope == "blocks"

    def test_verify_scope_fragments(self) -> None:
        args = self._capture_argv("--verify", "--verify-scope", "fragments")
        assert args.verify_scope == "fragments"

    def test_invalid_scope_rejected(self) -> None:
        with pytest.raises(SystemExit):
            self._capture_argv("--verify", "--verify-scope", "bogus")

    def test_fail_on_conflict_propagates(self) -> None:
        args = self._capture_argv("--verify", "--fail-on", "conflict")
        assert args.verify_fail_on == "conflict"

    def test_fail_on_never_propagates(self) -> None:
        args = self._capture_argv("--verify", "--fail-on", "never")
        assert args.verify_fail_on == "never"

    def test_invalid_fail_on_rejected(self) -> None:
        with pytest.raises(SystemExit):
            self._capture_argv("--verify", "--fail-on", "bogus")


# ---------------------------------------------------------------------------
# Dataclass surfaces — guard against accidental field changes
# ---------------------------------------------------------------------------


class TestDataclassShape:
    def test_file_entry_frozen(self) -> None:
        entry = FileVerifyEntry(rel_path="x.py", origin="base-template", status="unchanged")
        with pytest.raises(Exception):  # noqa: B017
            entry.rel_path = "y.py"  # type: ignore[misc]

    def test_block_entry_frozen(self) -> None:
        entry = BlockVerifyEntry(
            key="k",
            rel_path="r",
            feature_key="f",
            marker="m",
            status="unchanged",
        )
        with pytest.raises(Exception):  # noqa: B017
            entry.status = "user-modified"  # type: ignore[misc]

    def test_report_frozen(self) -> None:
        report = VerifyReport(worst="clean", summary={"unchanged": 0})
        with pytest.raises(Exception):  # noqa: B017
            report.worst = "drift"  # type: ignore[misc]

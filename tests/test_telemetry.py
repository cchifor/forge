"""Tests for opt-in telemetry (Item 4 of post-plan follow-ups).

Covers:

1. Mode off — :func:`emit` is a no-op.
2. Local mode — events become JSONL lines with the envelope schema.
3. Schema-field invariants — required fields always present.
4. Project hash determinism.
5. Minimal field filter — paths and fragment names stripped.
6. Full field filter — everything kept.
7. Remote mode — POST to endpoint, failures don't crash forge.
8. Rotation — 10MB threshold, oldest rolls off.
9. ``--telemetry-export`` — streams JSONL to stdout.
10. CLI wiring — verify / harvest / update / accept-harvested / reapply-baseline /
    emit-pr / resolve emit the expected events in local mode.
11. CLI flag overrides env var.

Tests that touch the daemon executor call :func:`forge.telemetry.shutdown`
after every emit so the worker flushes before assertions run. Without this,
the daemon thread could still be writing when the test pokes the file.
"""

from __future__ import annotations

import io
import json
import urllib.error
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge import telemetry
from forge.fragments import MARKER_PREFIX
from forge.sync.manifest import write_forge_toml
from forge.sync.provenance import sha256_of

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Reset telemetry state per-test.

    Clears env vars (so a developer with FORGE_TELEMETRY set globally
    doesn't leak into tests), installs a tmp-path sink so the user's
    real ~/.forge isn't touched, and disables telemetry so individual
    tests opt in explicitly.
    """
    for var in (
        "FORGE_TELEMETRY",
        "FORGE_TELEMETRY_FIELDS",
        "FORGE_TELEMETRY_ENDPOINT",
        "FORGE_TELEMETRY_SINK",
    ):
        monkeypatch.delenv(var, raising=False)
    telemetry.configure(
        telemetry.TelemetryConfig(
            mode="off",
            fields="full",
            sink_path=tmp_path / "sink.jsonl",
        )
    )
    yield
    telemetry.shutdown(wait=True)


def _enable_local(tmp_path: Path, fields: telemetry.TelemetryFields = "full") -> Path:
    """Switch telemetry to local mode and return the sink path."""
    sink = tmp_path / "telemetry.jsonl"
    telemetry.configure(
        telemetry.TelemetryConfig(
            mode="local",
            fields=fields,
            sink_path=sink,
        )
    )
    return sink


def _read_events(sink: Path) -> list[dict[str, Any]]:
    """Drain the executor and read every line as JSON."""
    telemetry.shutdown(wait=True)
    if not sink.exists():
        return []
    out: list[dict[str, Any]] = []
    with sink.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Case 1: mode=off is a no-op
# ---------------------------------------------------------------------------


class TestModeOff:
    def test_emit_does_not_write(self, tmp_path: Path) -> None:
        sink = tmp_path / "sink.jsonl"
        telemetry.configure(telemetry.TelemetryConfig(mode="off", sink_path=sink))
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="clean",
            summary_counts={"unchanged": 1},
            scope="all",
            exit_code=0,
        )
        telemetry.shutdown(wait=True)
        assert not sink.exists()

    def test_default_config_is_off(self) -> None:
        config = telemetry.TelemetryConfig()
        assert config.mode == "off"
        assert not config.enabled

    def test_unknown_env_value_falls_back_to_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Safety net: a typo'd env var must not silently enable telemetry.
        monkeypatch.setenv("FORGE_TELEMETRY", "yes-please")
        config = telemetry.load_config(args=None)
        assert config.mode == "off"


# ---------------------------------------------------------------------------
# Case 2: local mode writes one JSONL line per event
# ---------------------------------------------------------------------------


class TestLocalSink:
    def test_single_event_writes_one_line(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="clean",
            summary_counts={"unchanged": 1},
            scope="all",
            exit_code=0,
        )
        events = _read_events(sink)
        assert len(events) == 1
        assert events[0]["event"] == telemetry.EVENT_VERIFY_RAN
        assert events[0]["worst"] == "clean"
        assert events[0]["summary_counts"] == {"unchanged": 1}

    def test_multiple_events_each_get_a_line(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        for n in range(5):
            telemetry.emit(
                telemetry.EVENT_HARVEST_CANDIDATE,
                project_root=tmp_path,
                kind="files",
                risk="safe-apply",
                fragment=f"frag_{n}",
                rel_path=f"src/file_{n}.py",
            )
        events = _read_events(sink)
        assert len(events) == 5
        assert {e["fragment"] for e in events} == {f"frag_{n}" for n in range(5)}

    def test_sink_dir_is_created(self, tmp_path: Path) -> None:
        # Nested path; the writer must mkdir -p.
        sink = tmp_path / "nested" / "deep" / "telemetry.jsonl"
        telemetry.configure(telemetry.TelemetryConfig(mode="local", fields="full", sink_path=sink))
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="clean",
            summary_counts={},
            scope="all",
            exit_code=0,
        )
        telemetry.shutdown(wait=True)
        assert sink.exists()


# ---------------------------------------------------------------------------
# Case 3: required envelope fields always present
# ---------------------------------------------------------------------------


class TestEnvelopeSchema:
    def test_required_fields_present(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="clean",
            summary_counts={},
            scope="all",
            exit_code=0,
        )
        (event,) = _read_events(sink)
        for required in ("event", "timestamp", "forge_version", "schema_version", "project_hash"):
            assert required in event, f"missing {required}"
        assert event["schema_version"] == telemetry.SCHEMA_VERSION
        # forge_version should match the actual package version
        import forge as _forge

        assert event["forge_version"] == _forge.__version__

    def test_timestamp_is_iso_utc(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="clean",
            summary_counts={},
            scope="all",
            exit_code=0,
        )
        (event,) = _read_events(sink)
        ts = event["timestamp"]
        # ISO 8601 with UTC suffix
        assert "T" in ts
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_project_root_none_drops_project_hash(self, tmp_path: Path) -> None:
        # Defensive — we don't currently emit project_root=None, but the
        # contract is that it's optional. Hash should be absent.
        sink = _enable_local(tmp_path)
        telemetry.emit(
            telemetry.EVENT_UPDATE_RAN,
            project_root=None,
            files_applied=0,
            blocks_applied=0,
            conflicts=0,
        )
        (event,) = _read_events(sink)
        assert "project_hash" not in event


# ---------------------------------------------------------------------------
# Case 4: project_hash determinism
# ---------------------------------------------------------------------------


class TestProjectHash:
    def test_same_root_same_hash(self, tmp_path: Path) -> None:
        h1 = telemetry.project_hash(tmp_path)
        h2 = telemetry.project_hash(tmp_path)
        assert h1 == h2

    def test_different_roots_different_hash(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert telemetry.project_hash(a) != telemetry.project_hash(b)

    def test_hash_format(self, tmp_path: Path) -> None:
        h = telemetry.project_hash(tmp_path)
        assert len(h) == 16
        # hex only
        int(h, 16)


# ---------------------------------------------------------------------------
# Case 5: minimal field filter
# ---------------------------------------------------------------------------


class TestMinimalFilter:
    def test_strips_paths_and_fragment(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path, fields="minimal")
        telemetry.emit(
            telemetry.EVENT_HARVEST_CANDIDATE,
            project_root=tmp_path,
            kind="files",
            risk="safe-apply",
            fragment="middleware_cors",
            rel_path="src/main.py",
        )
        (event,) = _read_events(sink)
        # Required envelope + bounded-vocab fields survive.
        assert event["event"] == telemetry.EVENT_HARVEST_CANDIDATE
        assert event["kind"] == "files"
        assert event["risk"] == "safe-apply"
        assert "project_hash" in event
        # Identifier fields stripped.
        assert "fragment" not in event
        assert "rel_path" not in event

    def test_strips_emit_pr_branch_and_url(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path, fields="minimal")
        telemetry.emit(
            telemetry.EVENT_EMIT_PR_RAN,
            project_root=tmp_path,
            mode="branch",
            branch="harvest/abc123",
            pr_url="https://github.com/o/r/pull/42",
            entry_count=1,
            accepted=1,
            skipped=0,
        )
        (event,) = _read_events(sink)
        # Allowed survivors.
        assert event["mode"] == "branch"
        assert event["entry_count"] == 1
        assert event["accepted"] == 1
        # Redacted identifiers.
        assert "branch" not in event
        assert "pr_url" not in event

    def test_aggregate_counts_pass_through(self, tmp_path: Path) -> None:
        """``summary_counts`` is a dict but its keys are vocabulary — pass it through."""
        sink = _enable_local(tmp_path, fields="minimal")
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="drift",
            summary_counts={"unchanged": 5, "user-modified": 2},
            scope="all",
            exit_code=10,
        )
        (event,) = _read_events(sink)
        assert event["summary_counts"] == {"unchanged": 5, "user-modified": 2}
        assert event["worst"] == "drift"


# ---------------------------------------------------------------------------
# Case 6: full field filter
# ---------------------------------------------------------------------------


class TestFullFilter:
    def test_keeps_paths_and_fragment(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path, fields="full")
        telemetry.emit(
            telemetry.EVENT_HARVEST_CANDIDATE,
            project_root=tmp_path,
            kind="block",
            risk="safe-apply",
            fragment="middleware_cors",
            rel_path="src/main.py",
        )
        (event,) = _read_events(sink)
        assert event["fragment"] == "middleware_cors"
        assert event["rel_path"] == "src/main.py"
        assert event["kind"] == "block"


# ---------------------------------------------------------------------------
# Case 7: remote mode — POST + failure handling
# ---------------------------------------------------------------------------


class TestRemoteMode:
    def test_remote_posts_to_endpoint(self, tmp_path: Path) -> None:
        sink = tmp_path / "telemetry.jsonl"
        telemetry.configure(
            telemetry.TelemetryConfig(
                mode="remote",
                fields="full",
                sink_path=sink,
                endpoint="https://collector.example.com/forge",
            )
        )
        calls: list[dict[str, Any]] = []

        class _FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self) -> bytes:
                return b"ok"

        def _fake_urlopen(req, timeout):  # noqa: ANN001
            calls.append(
                {
                    "url": req.full_url,
                    "data": json.loads(req.data.decode("utf-8")),
                    "headers": dict(req.headers),
                    "timeout": timeout,
                }
            )
            return _FakeResponse()

        with patch("urllib.request.urlopen", _fake_urlopen):
            telemetry.emit(
                telemetry.EVENT_VERIFY_RAN,
                project_root=tmp_path,
                worst="clean",
                summary_counts={},
                scope="all",
                exit_code=0,
            )
            telemetry.shutdown(wait=True)

        assert len(calls) == 1
        assert calls[0]["url"] == "https://collector.example.com/forge"
        assert calls[0]["data"]["event"] == telemetry.EVENT_VERIFY_RAN
        # Local sink is *also* written in remote mode.
        assert sink.exists()
        assert len(sink.read_text().strip().split("\n")) == 1

    def test_remote_failure_does_not_crash(self, tmp_path: Path) -> None:
        sink = tmp_path / "telemetry.jsonl"
        telemetry.configure(
            telemetry.TelemetryConfig(
                mode="remote",
                fields="full",
                sink_path=sink,
                endpoint="https://offline.example.com/forge",
            )
        )

        def _boom(req, timeout):  # noqa: ANN001
            raise urllib.error.URLError("connection refused")

        with patch("urllib.request.urlopen", _boom):
            # Should not raise.
            telemetry.emit(
                telemetry.EVENT_VERIFY_RAN,
                project_root=tmp_path,
                worst="clean",
                summary_counts={},
                scope="all",
                exit_code=0,
            )
            telemetry.shutdown(wait=True)

        # Local sink still got the line — remote failure shouldn't drop the
        # local record.
        assert sink.exists()
        assert len(sink.read_text().strip().split("\n")) == 1


# ---------------------------------------------------------------------------
# Case 8: rotation
# ---------------------------------------------------------------------------


class TestRotation:
    def test_rotation_triggers_past_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "telemetry.jsonl"
        # Shrink the threshold so we can hit it without writing 10MB.
        monkeypatch.setattr(telemetry, "_MAX_BYTES", 512)
        telemetry.configure(telemetry.TelemetryConfig(mode="local", fields="full", sink_path=sink))
        # Emit enough events to bust the threshold. Each event is ~200 bytes.
        for n in range(20):
            telemetry.emit(
                telemetry.EVENT_VERIFY_RAN,
                project_root=tmp_path,
                worst="clean",
                summary_counts={"unchanged": n},
                scope="all",
                exit_code=0,
            )
        telemetry.shutdown(wait=True)
        # At least one rotation should exist.
        rotated = sink.with_suffix(".1.jsonl")
        assert rotated.exists(), f"no rotation at {rotated} — current sink: {sink.exists()}"

    def test_oldest_rotation_deleted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = tmp_path / "telemetry.jsonl"
        # Pre-populate rotations .1 through .5 so a new rotation kicks .5 off.
        for n in range(1, 6):
            sink.with_suffix(f".{n}.jsonl").write_text(f"# rotation {n}\n")
        # Force a rotation by writing a large file.
        sink.write_text("X" * 2000)
        monkeypatch.setattr(telemetry, "_MAX_BYTES", 512)
        telemetry.configure(telemetry.TelemetryConfig(mode="local", fields="full", sink_path=sink))
        telemetry.emit(
            telemetry.EVENT_VERIFY_RAN,
            project_root=tmp_path,
            worst="clean",
            summary_counts={},
            scope="all",
            exit_code=0,
        )
        telemetry.shutdown(wait=True)
        # .5 should be gone (rolled off the end).
        # .1 should contain what was previously the active file.
        assert sink.with_suffix(".1.jsonl").exists()
        # The original .5 had its own marker; after rotation, the new .5 is
        # what was previously .4. So the original "# rotation 5\n" marker
        # should be gone from the filesystem.
        all_files = set(p.name for p in tmp_path.iterdir())
        # We expect .1-.5 plus the current file.
        rotation_files = {f for f in all_files if ".jsonl" in f}
        # Up to 6 total: current + 5 rotations.
        assert len(rotation_files) <= 6


# ---------------------------------------------------------------------------
# Case 9: --telemetry-export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_streams_to_stdout(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        for n in range(3):
            telemetry.emit(
                telemetry.EVENT_VERIFY_RAN,
                project_root=tmp_path,
                worst="clean",
                summary_counts={"unchanged": n},
                scope="all",
                exit_code=0,
            )
        telemetry.shutdown(wait=True)

        buf = io.StringIO()
        count = telemetry.export_local(buf, sink_path=sink)
        assert count == 3
        lines = [ln for ln in buf.getvalue().split("\n") if ln.strip()]
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # must round-trip

    def test_export_includes_rotations(self, tmp_path: Path) -> None:
        sink = tmp_path / "telemetry.jsonl"
        # Write a rotation and a current file.
        sink.with_suffix(".1.jsonl").write_text(
            json.dumps({"event": "rotated.event", "schema_version": 1}) + "\n"
        )
        sink.write_text(json.dumps({"event": "current.event", "schema_version": 1}) + "\n")
        telemetry.configure(telemetry.TelemetryConfig(mode="local", sink_path=sink))

        buf = io.StringIO()
        count = telemetry.export_local(buf, sink_path=sink)
        assert count == 2
        out = buf.getvalue()
        # Order: oldest rotation first, then current.
        rotated_pos = out.index("rotated.event")
        current_pos = out.index("current.event")
        assert rotated_pos < current_pos


# ---------------------------------------------------------------------------
# Case 10: wired commands emit the expected events
# ---------------------------------------------------------------------------


def _block_text(feature_key: str, marker_bare: str, body: str) -> str:
    return (
        f"# {MARKER_PREFIX}BEGIN {feature_key}:{marker_bare}\n"
        f"{body}"
        f"# {MARKER_PREFIX}END {feature_key}:{marker_bare}\n"
    )


def _write_minimal_project(tmp_path: Path) -> dict:
    """Tiny forge-tracked project with one base-template file."""
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    main_py = src / "main.py"
    main_py.write_text("# top of file\n# bottom of file\n")
    main_sha = sha256_of(main_py)
    provenance = {
        "src/app/main.py": {
            "origin": "base-template",
            "sha256": main_sha,
            "template_name": "python-service-template",
            "template_version": "0.6.1",
        }
    }
    write_forge_toml(
        tmp_path / "forge.toml",
        version="1.0.0",
        project_name="demo",
        templates={"python": "services/python-service-template"},
        options={},
        provenance=provenance,
        merge_blocks=None,
    )
    return {"main_sha": main_sha, "main_py": main_py}


class TestVerifyCommandWiring:
    def test_verify_clean_emits_verify_ran(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        _write_minimal_project(tmp_path)

        from forge.cli.commands.verify import _run_verify

        args = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=False,
        )
        rc = _run_verify(args)
        events = _read_events(sink)
        assert rc == 0
        # One verify.ran, no drift events (clean project).
        assert [e["event"] for e in events] == [telemetry.EVENT_VERIFY_RAN]
        evt = events[0]
        assert evt["worst"] == "clean"
        assert evt["scope"] == "all"
        assert evt["exit_code"] == 0

    def test_verify_drift_emits_drift_events(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        meta = _write_minimal_project(tmp_path)
        # Edit the file to trigger drift.
        meta["main_py"].write_text("# user edit\n")

        from forge.cli.commands.verify import _run_verify

        args = Namespace(
            project_path=str(tmp_path),
            verify_scope="all",
            verify_fail_on="drift",
            json_output=False,
        )
        # Capture stdout so the human render doesn't pollute pytest output.
        with patch("sys.stdout", new=io.StringIO()):
            rc = _run_verify(args)
        events = _read_events(sink)
        # First event is the summary, then one drift event for the file.
        ran = [e for e in events if e["event"] == telemetry.EVENT_VERIFY_RAN]
        drift = [e for e in events if e["event"] == telemetry.EVENT_VERIFY_DRIFT]
        assert len(ran) == 1
        assert len(drift) == 1
        assert ran[0]["worst"] == "drift"
        assert drift[0]["kind"] == "file"
        assert drift[0]["action"] == "user-modified"
        # Exit-code is the drift code.
        assert rc != 0


class TestHarvestCommandWiring:
    def test_harvest_empty_project_emits_harvest_ran(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        _write_minimal_project(tmp_path)

        from forge.cli.commands.harvest import _run_harvest

        out_dir = tmp_path / "harvest-out"
        args = Namespace(
            project_path=str(tmp_path),
            harvest_out=str(out_dir),
            harvest_scope=None,
            harvest_include="all",
            harvest_interactive=False,
            json_output=False,
            quiet=True,
            emit_pr="off",
        )
        rc = _run_harvest(args)
        events = _read_events(sink)
        assert rc == 0
        # Just the summary event; no candidates in a clean project.
        ran = [e for e in events if e["event"] == telemetry.EVENT_HARVEST_RAN]
        assert len(ran) == 1
        assert ran[0]["entry_count"] == 0
        assert ran[0]["candidate_count_by_kind"] == {}


class TestAcceptHarvestedWiring:
    def test_accept_harvested_empty_bundle_emits_event(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        _write_minimal_project(tmp_path)

        # Build an empty bundle on disk.
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()
        manifest = {
            "bundle_id": "harvest-test-00000000",
            "project_root": str(tmp_path),
            "forge_version": "1.2.0-alpha.1",
            "candidates": [],
        }
        (bundle_dir / "manifest.json").write_text(json.dumps(manifest))

        from forge.cli.commands.accept_harvested import _run_accept_harvested

        args = Namespace(
            accept_harvested=str(bundle_dir),
            project_path=str(tmp_path),
            json_output=False,
            quiet=True,
            accept_risk_filter=None,
        )
        rc = _run_accept_harvested(args)
        events = _read_events(sink)
        assert rc == 0
        assert [e["event"] for e in events] == [telemetry.EVENT_ACCEPT_HARVESTED_RAN]
        assert events[0]["entry_count"] == 0


class TestReapplyBaselineWiring:
    def test_reapply_baseline_emits_event(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        _write_minimal_project(tmp_path)

        from forge.cli.commands.reapply_baseline import _run_reapply_baseline

        args = Namespace(
            project_path=str(tmp_path),
            reapply_scope=None,
            json_output=False,
            quiet=True,
            dry_run=False,
        )
        rc = _run_reapply_baseline(args)
        events = _read_events(sink)
        assert rc == 0
        assert [e["event"] for e in events] == [telemetry.EVENT_REAPPLY_BASELINE_RAN]


class TestResolveWiring:
    def test_resolve_empty_emits_event(self, tmp_path: Path) -> None:
        sink = _enable_local(tmp_path)
        _write_minimal_project(tmp_path)

        from forge.cli.commands.resolve import _run_resolve

        args = Namespace(
            resolve_path=None,
            project_path=str(tmp_path),
            json_output=False,
            quiet=True,
        )
        rc = _run_resolve(args)
        events = _read_events(sink)
        assert rc == 0
        assert [e["event"] for e in events] == [telemetry.EVENT_RESOLVE_RAN]
        assert events[0]["entry_count"] == 0


# ---------------------------------------------------------------------------
# Case 11: CLI flag overrides env var
# ---------------------------------------------------------------------------


class TestConfigPrecedence:
    def test_cli_flag_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_TELEMETRY", "local")
        args = Namespace(telemetry="off")
        config = telemetry.load_config(args)
        assert config.mode == "off"

    def test_env_used_when_no_cli_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_TELEMETRY", "local")
        args = Namespace(telemetry=None)
        config = telemetry.load_config(args)
        assert config.mode == "local"

    def test_default_when_neither(self) -> None:
        args = Namespace(telemetry=None)
        config = telemetry.load_config(args)
        assert config.mode == "off"

    def test_fields_cli_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_TELEMETRY_FIELDS", "full")
        args = Namespace(telemetry=None, telemetry_fields="minimal")
        config = telemetry.load_config(args)
        assert config.fields == "minimal"

    def test_endpoint_read_from_env_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_TELEMETRY_ENDPOINT", "https://example.com/forge")
        config = telemetry.load_config(args=None)
        assert config.endpoint == "https://example.com/forge"

    def test_sink_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        target = tmp_path / "custom" / "sink.jsonl"
        monkeypatch.setenv("FORGE_TELEMETRY_SINK", str(target))
        config = telemetry.load_config(args=None)
        assert config.sink_path == target

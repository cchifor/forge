"""End-to-end coverage for the ``--log-json`` CLI flag (v2 Theme 10).

The unit tests in ``tests/test_forge_logging.py`` exercise the formatter
and ``configure_logging`` kwarg paths directly. This module instead drives
the real ``cli.main()`` entry point with ``--log-json`` set, captures
stderr, and confirms that structured events emitted during the CLI
lifecycle (``phase_timer``-wrapped phases inside the generator, an
explicit ``log_event`` we inject at the end of the mocked ``generate``)
arrive as NDJSON on stderr. The negative path asserts that without
``--log-json`` the same lifecycle emits human-readable text instead.

These tests anchor the front-door contract a downstream agent depends on
when it shells out to ``forge new --log-json …`` and parses the trace.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from forge import cli
from forge.logging import get_logger, log_event, phase_timer


@pytest.fixture(autouse=True)
def _reset_forge_root_handlers():
    """Strip forge-owned handlers around each test.

    ``cli.main()`` installs a handler on the ``forge`` root logger via
    ``configure_logging``. The autouse fixture in ``test_forge_logging.py``
    only covers that module; here we need the same scrub so tests don't
    leak handlers into one another or into the wider pytest run.
    """
    root = logging.getLogger("forge")
    saved = list(root.handlers)
    saved_level = root.level
    for h in list(root.handlers):
        if getattr(h, "_forge_owned", False):
            root.removeHandler(h)
    yield
    for h in list(root.handlers):
        if getattr(h, "_forge_owned", False):
            root.removeHandler(h)
    root.level = saved_level
    for h in saved:
        if not getattr(h, "_forge_owned", False) and h not in root.handlers:
            root.addHandler(h)


def _fake_generate_emitting_phase(project_root: Path):
    """Stand-in for ``forge.generator.generate`` that emits the same
    shape of structured events the real generator emits via ``phase_timer``.
    """

    def _generate(config, quiet=False, dry_run=False):  # noqa: ARG001
        logger = get_logger("generator")
        with phase_timer(logger, "generate.resolve"):
            pass
        with phase_timer(logger, "generate.write_forge_toml"):
            pass
        log_event(logger, "generate.complete", project=str(project_root))
        project_root.mkdir(parents=True, exist_ok=True)
        return project_root

    return _generate


def _argv_for(tmp_path: Path, *extra: str) -> list[str]:
    """Build a minimal headless argv that bypasses interactive prompts."""
    return [
        "forge",
        "--yes",
        "--quiet",
        "--no-docker",
        "--project-name",
        "LogJsonProbe",
        "--output-dir",
        str(tmp_path),
        "--backend-language",
        "python",
        *extra,
    ]


class TestLogJsonEndToEnd:
    """``forge … --log-json`` produces JSONL on stderr."""

    def test_log_json_emits_ndjson_to_stderr(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        project_root = tmp_path / "logjsonprobe"
        monkeypatch.setattr(sys, "argv", _argv_for(tmp_path, "--log-json"))

        with patch(
            "forge.cli.main.generate",
            side_effect=_fake_generate_emitting_phase(project_root),
        ):
            cli.main()

        err = capsys.readouterr().err
        # Every non-empty line on stderr should parse as JSON. (We allow
        # the line set to include other forge-emitted events such as
        # plugin-load notices; the contract is "all of stderr is JSONL".)
        lines = [ln for ln in err.splitlines() if ln.strip()]
        assert lines, "expected at least one JSON line on stderr"

        parsed = []
        for ln in lines:
            try:
                parsed.append(json.loads(ln))
            except json.JSONDecodeError as exc:
                pytest.fail(
                    f"stderr line is not JSON: {ln!r} (error: {exc})"
                )

        events = {p.get("event") for p in parsed}
        # The two phase_timer wrappers emit on exit with the phase name as
        # the event; the explicit log_event closes the trace.
        assert "generate.resolve" in events
        assert "generate.write_forge_toml" in events
        assert "generate.complete" in events

        # Every phase_timer record carries duration_ms + status=ok.
        phase_records = [
            p for p in parsed if p.get("event") in {
                "generate.resolve", "generate.write_forge_toml",
            }
        ]
        for rec in phase_records:
            assert rec["status"] == "ok"
            assert isinstance(rec["duration_ms"], int)
            assert "ts" in rec
            assert rec["logger"] == "forge.generator"

    def test_without_log_json_no_json_on_stderr(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        project_root = tmp_path / "textmode"
        # Force text mode regardless of any inherited env var.
        monkeypatch.delenv("FORGE_LOG_FORMAT", raising=False)
        monkeypatch.setattr(sys, "argv", _argv_for(tmp_path))

        with patch(
            "forge.cli.main.generate",
            side_effect=_fake_generate_emitting_phase(project_root),
        ):
            cli.main()

        err = capsys.readouterr().err
        # The phase events should still appear (as text), but the lines
        # must NOT be parseable JSON objects.
        for ln in err.splitlines():
            stripped = ln.strip()
            if not stripped or not stripped.startswith("{"):
                continue
            with pytest.raises(json.JSONDecodeError):
                # A text-format line that happens to start with '{' would
                # otherwise slip past this assertion. None should.
                json.loads(stripped)


class TestLogJsonCorrelationId:
    """Every JSON event in a single CLI invocation shares one ``correlation_id``."""

    def test_correlation_id_present_and_stable(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        project_root = tmp_path / "corrprobe"
        monkeypatch.setattr(sys, "argv", _argv_for(tmp_path, "--log-json"))

        with patch(
            "forge.cli.main.generate",
            side_effect=_fake_generate_emitting_phase(project_root),
        ):
            cli.main()

        err = capsys.readouterr().err
        parsed = [
            json.loads(ln) for ln in err.splitlines() if ln.strip()
        ]
        # Every record (phase_timer + explicit log_event) must carry the
        # correlation_id stamped at CLI entry.
        cids = {rec.get("correlation_id") for rec in parsed if "event" in rec}
        cids.discard(None)
        assert len(cids) == 1, (
            f"expected a single correlation_id across all events, got {cids!r}"
        )
        cid = next(iter(cids))
        # UUID-shape sanity: hyphen-separated 36-char string.
        assert isinstance(cid, str)
        assert len(cid) == 36
        assert cid.count("-") == 4

    def test_each_invocation_gets_a_fresh_correlation_id(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        seen: list[str] = []

        for slug in ("first", "second"):
            project_root = tmp_path / slug
            monkeypatch.setattr(
                sys, "argv", _argv_for(tmp_path, "--log-json")
            )
            with patch(
                "forge.cli.main.generate",
                side_effect=_fake_generate_emitting_phase(project_root),
            ):
                cli.main()
            err = capsys.readouterr().err
            cids = {
                json.loads(ln).get("correlation_id")
                for ln in err.splitlines()
                if ln.strip()
            }
            cids.discard(None)
            assert len(cids) == 1
            seen.append(next(iter(cids)))

        assert seen[0] != seen[1], (
            "correlation_id should reset per CLI invocation"
        )

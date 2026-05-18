"""Regression tests for ``run_lane_smoke``'s diagnostic dump on failure.

The bug we guard against here: when ``docker compose up`` itself
fails — e.g. a backend container exits non-zero during bring-up —
``run_lane_smoke`` used to early-return without invoking
``_dump_compose_diagnostics``, because the dump was gated on
``compose_up = True`` and that flag was only set AFTER the up-result
check. Result: the failed containers' logs (the exact data we need
to debug the failure) were never captured into ``FORGE_MATRIX_LOG_DIR``,
so the CI artifact upload (``if: failure()``) had nothing to upload —
exactly when the failure happened.

These tests mock just enough of the subprocess + filesystem surface
to drive the failure path without spinning up real Docker:

* ``subprocess.run`` is patched at the module level — the call for
  ``docker compose up`` returns a non-zero exit. Other calls (the
  ``logs`` / ``ps`` inside ``_dump_compose_diagnostics``) are
  swallowed by a default-OK return so the dump executes its inner
  body.
* ``shutil.which`` is patched to claim docker is on PATH (the lane
  short-circuits to ``skip`` otherwise).
* ``forge.generator.generate`` is patched to write a minimal
  ``docker-compose.yml`` into the tmp project root so the lane's
  existence check passes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from tests.matrix.runner import Scenario, run_lane_smoke


def _make_scenario() -> Scenario:
    return Scenario(
        name="diagtest",
        description="diagnostic-dump regression",
        lanes=("smoke",),
        port_base=9999,
        expected_files=(),
        config={
            "project_name": "Diag Test",
            "include_keycloak": False,
            "backends": [
                {
                    "name": "api",
                    "language": "python",
                    "server_port": 9999,
                    "python_version": "3.13",
                }
            ],
            "frontend": "none",
        },
    )


def _fake_generate(tmp_dir_factory):
    """Factory that returns a ``generate`` stand-in writing a stub project.

    The closure captures the parent tmp dir so the function signature
    matches ``generate(project_config, quiet=..., dry_run=...)``.
    """

    def _inner(*_args: Any, **_kwargs: Any) -> Path:
        # ``run_lane_smoke`` reads ``project_config.backends`` etc. from
        # the second positional arg only AFTER generate returns; we just
        # need to return a path whose ``docker-compose.yml`` exists.
        project_root = tmp_dir_factory / "stub-project"
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / "docker-compose.yml").write_text(
            "services:\n  api:\n    image: nonexistent\n",
            encoding="utf-8",
        )
        return project_root

    return _inner


def test_compose_up_failure_dumps_diagnostics(tmp_path, monkeypatch):
    """When ``compose up`` fails, ``_dump_compose_diagnostics`` MUST fire.

    Pre-fix behaviour: the function early-returned a FAIL ``LaneResult``
    before setting ``compose_up = True``, so the ``finally`` block's
    diagnostic dump was skipped. The CI artifact for this scenario
    would then be empty even though the up-failure produced exactly
    the container exit logs we needed.
    """
    log_dir = tmp_path / "matrix-logs"
    monkeypatch.setenv("FORGE_MATRIX_LOG_DIR", str(log_dir))

    # Pretend docker is on PATH — the lane short-circuits to skip
    # otherwise.
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    # Stub generate() so we don't pay for a real generate. The
    # function returns a project_root with a docker-compose.yml file
    # the lane can find.
    monkeypatch.setattr(
        "forge.generator.generate", _fake_generate(tmp_path)
    )

    # Stub _build_config + validate to no-op so the lane proceeds.
    fake_config = MagicMock()
    fake_config.backends = []
    fake_config.validate = MagicMock(return_value=None)
    monkeypatch.setattr(
        "forge.cli.builder._build_config",
        lambda ns, cfg: fake_config,
    )

    # Track which subprocess.run invocations happened, returning a
    # failing exit for the ``up`` call and success for any subsequent
    # diagnostic call (logs, ps).
    seen_invocations: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen_invocations.append(list(cmd))
        # The ``up -d --wait`` call exits non-zero (compose-up failure).
        if "up" in cmd and "-d" in cmd:
            result = MagicMock(spec=subprocess.CompletedProcess)
            result.returncode = 1
            result.stdout = ""
            result.stderr = "Error: container 'api' exited with code 3\n"
            return result
        # Diagnostic logs / ps calls run inside a ``with`` block that
        # uses ``stdout=fh`` — the file handle is passed in kwargs.
        # Pretend success so the dump completes.
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        # Write something to the redirected stdout file if present so
        # the dump's artifact files are not empty.
        if "stdout" in kwargs and hasattr(kwargs["stdout"], "write"):
            kwargs["stdout"].write("compose diagnostic line\n")
        return result

    monkeypatch.setattr("subprocess.run", fake_run)

    # Drive the lane.
    result = run_lane_smoke(_make_scenario())

    # The lane reports failure as expected …
    assert result.status == "fail", f"expected fail, got {result.status}: {result.details}"
    assert "docker compose up failed" in result.details

    # … and crucially, ``_dump_compose_diagnostics`` ran — we can
    # verify by the artifact files it would have created.
    log_file = log_dir / "diagtest.log"
    ps_file = log_dir / "diagtest.ps"
    assert log_file.exists(), (
        f"FORGE_MATRIX_LOG_DIR missing {log_file} — diagnostic dump did not fire on "
        f"compose-up failure path; invocations: {seen_invocations}"
    )
    assert ps_file.exists(), (
        f"FORGE_MATRIX_LOG_DIR missing {ps_file} — diagnostic dump did not fire on "
        f"compose-up failure path; invocations: {seen_invocations}"
    )


def test_diagnostics_dump_skipped_when_log_dir_unset(tmp_path, monkeypatch):
    """Without ``FORGE_MATRIX_LOG_DIR``, the dump must NOT crash the lane.

    Local invocations (developer machines, ``--scenario X --lane smoke``
    in IDE) don't set the env var. The lane should still return a
    clean FAIL/OK result without trying to write to a None path.
    """
    monkeypatch.delenv("FORGE_MATRIX_LOG_DIR", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker" if name == "docker" else None)
    monkeypatch.setattr(
        "forge.generator.generate", _fake_generate(tmp_path)
    )

    fake_config = MagicMock()
    fake_config.backends = []
    fake_config.validate = MagicMock(return_value=None)
    monkeypatch.setattr(
        "forge.cli.builder._build_config",
        lambda ns, cfg: fake_config,
    )

    def fake_run(cmd, **_kwargs):
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 1 if ("up" in cmd and "-d" in cmd) else 0
        result.stdout = ""
        result.stderr = "boom\n"
        return result

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_lane_smoke(_make_scenario())
    assert result.status == "fail"

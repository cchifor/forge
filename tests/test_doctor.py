"""Tests for `forge doctor` (4.6 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.doctor import (
    CheckResult,
    DoctorReport,
    check_forge_toml,
    check_port_free,
    check_tool_on_path,
    check_ts_morph_toolchain,
    render_text,
    run,
)


class TestCheckResult:
    def test_as_dict(self) -> None:
        r = CheckResult(name="x", status="ok", detail="fine")
        assert r.as_dict() == {"name": "x", "status": "ok", "detail": "fine", "fix": None}


class TestDoctorReport:
    def test_worst_aggregates(self) -> None:
        report = DoctorReport(results=[
            CheckResult("a", "ok", ""),
            CheckResult("b", "warn", ""),
            CheckResult("c", "ok", ""),
        ])
        assert report.worst == "warn"

    def test_worst_fail_dominates_warn(self) -> None:
        report = DoctorReport(results=[
            CheckResult("a", "warn", ""),
            CheckResult("b", "fail", ""),
        ])
        assert report.worst == "fail"

    def test_worst_all_ok(self) -> None:
        report = DoctorReport(results=[CheckResult("a", "ok", "")])
        assert report.worst == "ok"


class TestCheckToolOnPath:
    def test_found_tool(self) -> None:
        # Python's own executable is always on PATH while running pytest.
        result = check_tool_on_path("python")
        assert result.status == "ok"

    def test_missing_tool(self) -> None:
        result = check_tool_on_path("this_tool_does_not_exist_anywhere")
        assert result.status == "fail"
        assert "not found" in result.detail


class TestCheckPortFree:
    def test_free_port(self) -> None:
        # Pick an unusual port — unlikely to be in use by system services.
        result = check_port_free(49123)
        assert result.status in ("ok", "warn")

    def test_occupied_port_is_warn_not_fail(self) -> None:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            _, port = s.getsockname()
            s.listen()
            result = check_port_free(port)
            assert result.status == "warn"
            assert "in use" in result.detail
        finally:
            s.close()


class TestCheckForgeToml:
    def test_no_forge_toml_ok(self, tmp_path: Path) -> None:
        result = check_forge_toml(tmp_path)
        assert result.status == "ok"
        assert "no forge.toml" in result.detail

    def test_valid_forge_toml(self, tmp_path: Path) -> None:
        from forge.forge_toml import write_forge_toml

        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0a1",
            project_name="demo",
            templates={"python": "services/python-service-template"},
            options={},
        )
        result = check_forge_toml(tmp_path)
        assert result.status == "ok"
        assert "version=1.0.0a1" in result.detail

    def test_malformed_forge_toml(self, tmp_path: Path) -> None:
        (tmp_path / "forge.toml").write_text("not valid toml = = =")
        result = check_forge_toml(tmp_path)
        assert result.status == "fail"


class TestRenderText:
    def test_renders_each_check(self) -> None:
        report = DoctorReport(results=[
            CheckResult("tool:git", "ok", "found"),
            CheckResult("docker:daemon", "fail", "not running", fix="start it"),
        ])
        out = render_text(report)
        assert "[OK]" in out
        assert "[FAIL]" in out
        assert "start it" in out
        assert "Overall: [FAIL]" in out


class TestRun:
    def test_produces_non_empty_report(self, tmp_path: Path) -> None:
        report = run(tmp_path)
        assert report.results
        names = {r.name for r in report.results}
        assert "runtime:python" in names
        assert "forge.toml:presence" in names or "forge.toml:integrity" in names

    def test_includes_ts_morph_toolchain_check(self, tmp_path: Path) -> None:
        # P1.4 — the ts-morph status row must be in the standard run.
        report = run(tmp_path)
        names = {r.name for r in report.results}
        assert "ts-morph:toolchain" in names or "ts-morph:helper" in names


class TestCheckTsMorphToolchain:
    """P1.4 (1.1.0-alpha.2) — surface ts-morph reachability for FORGE_TS_AST."""

    def test_warn_when_node_not_on_path(self) -> None:
        # When ``shutil.which("node")`` returns None, the toolchain isn't
        # available; doctor surfaces it as a warning with an actionable
        # fix. The helper-missing branch is suppressed by patching
        # _HELPER_PATH.is_file() to True.
        from forge.injectors import ts_morph_sidecar

        with patch.object(ts_morph_sidecar, "_HELPER_PATH") as mock_path:
            mock_path.is_file.return_value = True
            with patch("forge.doctor.shutil.which", return_value=None):
                result = check_ts_morph_toolchain()
        assert result.status == "warn"
        assert "Node" in result.detail
        assert result.fix is not None
        assert "FORGE_TS_AST" in (result.fix or "")

    def test_warn_when_helper_missing(self, tmp_path: Path) -> None:
        # Packaging regression: helper script absent. Should warn (not
        # fail) so doctor doesn't escalate to a non-zero exit.
        from forge.injectors import ts_morph_sidecar

        missing_helper = tmp_path / "ts-morph-helper.mjs"
        with patch.object(ts_morph_sidecar, "_HELPER_PATH", missing_helper):
            result = check_ts_morph_toolchain()
        assert result.status == "warn"
        assert "helper missing" in result.detail.lower() or "missing" in result.detail.lower()

    def test_warn_when_ts_morph_not_reachable(self) -> None:
        # Node present but `require('ts-morph')` exits non-zero — warn.
        from forge.injectors import ts_morph_sidecar
        from forge.doctor import subprocess as doctor_subprocess

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = 1
                self.stdout = ""
                self.stderr = "Cannot find module 'ts-morph'"

        with patch.object(ts_morph_sidecar, "_HELPER_PATH") as mock_path:
            mock_path.is_file.return_value = True
            with patch("forge.doctor.shutil.which", return_value="/usr/bin/node"):
                with patch.object(
                    doctor_subprocess, "run", return_value=_FakeProc()
                ):
                    result = check_ts_morph_toolchain()
        assert result.status == "warn"
        assert "ts-morph" in result.detail
        assert "regex" in result.detail.lower() or "fallback" in result.detail.lower()

    def test_ok_when_reachable_and_env_set(self, monkeypatch) -> None:
        from forge.injectors import ts_morph_sidecar
        from forge.doctor import subprocess as doctor_subprocess

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""

        monkeypatch.setenv("FORGE_TS_AST", "1")
        with patch.object(ts_morph_sidecar, "_HELPER_PATH") as mock_path:
            mock_path.is_file.return_value = True
            with patch("forge.doctor.shutil.which", return_value="/usr/bin/node"):
                with patch.object(
                    doctor_subprocess, "run", return_value=_FakeProc()
                ):
                    result = check_ts_morph_toolchain()
        assert result.status == "ok"
        assert "active" in result.detail.lower() or "FORGE_TS_AST=1" in result.detail

    def test_ok_when_reachable_but_env_unset(self, monkeypatch) -> None:
        from forge.injectors import ts_morph_sidecar
        from forge.doctor import subprocess as doctor_subprocess

        class _FakeProc:
            def __init__(self) -> None:
                self.returncode = 0
                self.stdout = ""
                self.stderr = ""

        monkeypatch.delenv("FORGE_TS_AST", raising=False)
        with patch.object(ts_morph_sidecar, "_HELPER_PATH") as mock_path:
            mock_path.is_file.return_value = True
            with patch("forge.doctor.shutil.which", return_value="/usr/bin/node"):
                with patch.object(
                    doctor_subprocess, "run", return_value=_FakeProc()
                ):
                    result = check_ts_morph_toolchain()
        assert result.status == "ok"
        # Reachable but opt-in not set: hint for setting the env var.
        assert "FORGE_TS_AST" in result.detail

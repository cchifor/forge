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

"""Tests for generator failure modes (WS2): GeneratorError surfaces cleanly through CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import patch

import pytest

from forge.errors import GeneratorError
from forge.generator import _git_init, _run_backend_cmd, _run_copier

# -- _run_backend_cmd: required=True raises GeneratorError --------------------


class TestRunBackendCmdRequired:
    def test_required_failure_raises(self, tmp_path):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["npm", "install"],
                returncode=1,
                stdout="",
                stderr="ENOENT something\n",
            )
            with pytest.raises(GeneratorError) as exc_info:
                _run_backend_cmd(tmp_path, ["npm", "install"], "Install deps", required=True)
        assert "Install deps failed" in str(exc_info.value)
        assert "exit 1" in str(exc_info.value)

    def test_required_missing_tool_raises(self, tmp_path):
        with patch("forge.generator.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(GeneratorError) as exc_info:
                _run_backend_cmd(tmp_path, ["npm", "install"], "Install deps", required=True)
        assert "npm" in str(exc_info.value)
        assert "not found" in str(exc_info.value)

    def test_required_timeout_raises(self, tmp_path):
        with (
            patch(
                "forge.generator.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["npm"], timeout=300),
            ),
            pytest.raises(GeneratorError) as exc_info,
        ):
            _run_backend_cmd(tmp_path, ["npm", "install"], "Install deps", required=True)
        assert "timed out" in str(exc_info.value)

    def test_best_effort_failure_returns_false(self, tmp_path):
        # Default required=False preserves existing warn-and-continue behavior.
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["pytest"],
                returncode=1,
                stdout="",
                stderr="",
            )
            assert _run_backend_cmd(tmp_path, ["pytest"], "Tests") is False

    def test_best_effort_missing_tool_returns_false(self, tmp_path):
        with patch("forge.generator.subprocess.run", side_effect=FileNotFoundError):
            assert _run_backend_cmd(tmp_path, ["cargo", "build"], "Build") is False


# -- _git_init: each step is checked, failures raise GeneratorError -----------


class TestGitInitFailures:
    def test_init_failure_raises(self, tmp_path):
        # First subprocess call fails => `git init` step fails.
        def fail_first(*args, **kwargs):
            raise subprocess.CalledProcessError(returncode=1, cmd=args[0], stderr="oops\n")

        with patch("forge.generator.subprocess.run", side_effect=fail_first):
            with pytest.raises(GeneratorError) as exc_info:
                _git_init(tmp_path)
        assert "git init" in str(exc_info.value)

    def test_commit_failure_raises(self, tmp_path):
        # init + add succeed, commit fails (e.g. nothing to commit, hook rejection).
        calls: list[list[str]] = []

        def behavior(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1] == "commit":
                raise subprocess.CalledProcessError(returncode=1, cmd=cmd, stderr="hook fail\n")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("forge.generator.subprocess.run", side_effect=behavior):
            with pytest.raises(GeneratorError) as exc_info:
                _git_init(tmp_path)
        assert "git commit" in str(exc_info.value)
        assert "hook fail" in str(exc_info.value)
        assert len(calls) == 3  # init, add, commit attempted

    def test_git_not_installed_raises(self, tmp_path):
        with patch("forge.generator.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(GeneratorError) as exc_info:
                _git_init(tmp_path)
        assert "git executable not found" in str(exc_info.value).lower() or "git" in str(
            exc_info.value
        )


# -- _run_copier: Copier failures become GeneratorError -----------------------


class TestRunCopierFailures:
    def test_missing_template_raises(self, tmp_path):
        bogus = tmp_path / "does-not-exist"
        with pytest.raises(GeneratorError) as exc_info:
            _run_copier(bogus, tmp_path, {}, quiet=True)
        assert "Template not found" in str(exc_info.value)
        assert "does-not-exist" in str(exc_info.value)

    def test_copier_exception_wrapped(self, tmp_path):
        existing = tmp_path / "fake-template"
        existing.mkdir()
        with patch("forge.generator.run_copy", side_effect=RuntimeError("copier blew up")):
            with pytest.raises(GeneratorError) as exc_info:
                _run_copier(existing, tmp_path / "dst", {}, quiet=True)
        assert "fake-template" in str(exc_info.value)
        assert "copier blew up" in str(exc_info.value)


# -- CLI integration: GeneratorError → JSON envelope or stderr+exit(2) --------


class TestCliErrorRouting:
    def test_json_mode_emits_error_envelope(self, tmp_path, monkeypatch, capsys):
        from forge import cli

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "forge",
                "--json",
                "--yes",
                "--no-docker",
                "--project-name",
                "Errcase",
                "--output-dir",
                str(tmp_path),
                "--frontend",
                "none",
                "--no-auth",
            ],
        )

        with patch("forge.cli.main.generate", side_effect=GeneratorError("synthetic boom")):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 2

        out = capsys.readouterr().out
        # JSON mode redirects print() to stderr, so stdout should contain only the envelope.
        envelope = json.loads(out.strip().splitlines()[-1])
        # Post-Epic D, the envelope always carries the error's code (FORGE_ERROR
        # is the default when no subclass is chosen). `hint` and `context` keys
        # are only present when the error sets them.
        assert envelope["error"] == "synthetic boom"
        assert envelope["code"] == "FORGE_ERROR"
        assert "hint" not in envelope
        assert "context" not in envelope

    def test_text_mode_exits_2_with_message(self, tmp_path, monkeypatch, capsys):
        from forge import cli

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "forge",
                "--yes",
                "--quiet",
                "--no-docker",
                "--project-name",
                "Errcase",
                "--output-dir",
                str(tmp_path),
                "--frontend",
                "none",
                "--no-auth",
            ],
        )

        with patch("forge.cli.main.generate", side_effect=GeneratorError("synthetic boom")):
            with pytest.raises(SystemExit) as exc_info:
                cli.main()
        assert exc_info.value.code == 2

        err = capsys.readouterr().err
        assert "Generation failed" in err
        assert "synthetic boom" in err

"""Tests for forge.generator subprocess helpers and filesystem utilities."""

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.generator import (
    _cleanup_sub_git_repos,
    _force_remove_readonly,
    _git_init,
    _run_backend_cmd,
    _setup_backend,
)


# -- _run_backend_cmd ---------------------------------------------------------

class TestRunBackendCmd:
    def test_success(self, tmp_path, capsys):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["uv", "sync"], returncode=0, stdout="", stderr="",
            )
            result = _run_backend_cmd(tmp_path, ["uv", "sync"], "Install deps")

        assert result is True
        assert "[ok] Install deps" in capsys.readouterr().out

    def test_failure_prints_stderr(self, tmp_path, capsys):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["pytest"], returncode=1, stdout="",
                stderr="FAILED test_foo.py\nAssertionError\n",
            )
            result = _run_backend_cmd(tmp_path, ["pytest"], "Tests")

        assert result is False
        out = capsys.readouterr().out
        assert "[!!] Tests failed" in out
        assert "AssertionError" in out

    def test_failure_no_stderr(self, tmp_path, capsys):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["ruff"], returncode=1, stdout="", stderr="",
            )
            result = _run_backend_cmd(tmp_path, ["ruff"], "Lint")

        assert result is False
        out = capsys.readouterr().out
        assert "[!!]" in out
        # No stderr lines should be printed
        assert "       " not in out

    def test_passes_cwd(self, tmp_path):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            )
            _run_backend_cmd(tmp_path, ["echo"], "test")
            mock_run.assert_called_once()
            assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)


# -- _setup_backend -----------------------------------------------------------

class TestSetupBackend:
    def test_calls_five_commands(self, tmp_path):
        with patch("forge.generator._run_backend_cmd") as mock_cmd:
            mock_cmd.return_value = True
            _setup_backend(tmp_path)

        assert mock_cmd.call_count == 5
        descriptions = [call.args[2] for call in mock_cmd.call_args_list]
        assert descriptions == [
            "Install dependencies", "Lint fix", "Format", "Type check", "Tests",
        ]


# -- _force_remove_readonly ---------------------------------------------------

class TestForceRemoveReadonly:
    def test_clears_readonly_and_retries(self, tmp_path):
        f = tmp_path / "locked.txt"
        f.write_text("data")
        f.chmod(stat.S_IREAD)

        _force_remove_readonly(os.remove, str(f), None)
        assert not f.exists()


# -- _cleanup_sub_git_repos ---------------------------------------------------

class TestCleanupSubGitRepos:
    def test_removes_nested_git_dirs(self, tmp_path):
        # Create two child directories, each with a .git folder
        child_a = tmp_path / "backend"
        child_a.mkdir()
        (child_a / ".git").mkdir()
        (child_a / ".git" / "HEAD").write_text("ref: refs/heads/main")

        child_b = tmp_path / "frontend"
        child_b.mkdir()
        (child_b / ".git").mkdir()
        (child_b / ".git" / "config").write_text("[core]")

        _cleanup_sub_git_repos(tmp_path)

        assert not (child_a / ".git").exists()
        assert not (child_b / ".git").exists()
        # Parent directories should still exist
        assert child_a.exists()
        assert child_b.exists()

    def test_ignores_dirs_without_git(self, tmp_path):
        child = tmp_path / "src"
        child.mkdir()
        (child / "main.py").write_text("pass")

        _cleanup_sub_git_repos(tmp_path)
        assert (child / "main.py").exists()

    def test_ignores_files(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        _cleanup_sub_git_repos(tmp_path)  # should not raise


# -- _git_init ----------------------------------------------------------------

class TestGitInit:
    def test_runs_init_add_commit(self, tmp_path):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            )
            _git_init(tmp_path)

        assert mock_run.call_count == 3
        cmds = [call.args[0] for call in mock_run.call_args_list]
        assert cmds[0] == ["git", "init"]
        assert cmds[1] == ["git", "add", "."]
        assert cmds[2][0:2] == ["git", "commit"]

    def test_passes_project_root_as_cwd(self, tmp_path):
        with patch("forge.generator.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr="",
            )
            _git_init(tmp_path)

        for call in mock_run.call_args_list:
            assert call.kwargs["cwd"] == str(tmp_path)

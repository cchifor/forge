"""Tests for docker_manager lifecycle functions: _docker_running, boot, teardown."""

import subprocess
from unittest.mock import patch

import pytest

from forge.docker_manager import _docker_running, boot, teardown

# -- _docker_running ----------------------------------------------------------


class TestDockerRunning:
    def test_returns_true_when_docker_responds(self):
        with patch("forge.docker_manager.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["docker", "info"],
                returncode=0,
                stdout="",
                stderr="",
            )
            assert _docker_running() is True

    def test_returns_false_on_nonzero_exit(self):
        with patch("forge.docker_manager.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["docker", "info"],
                returncode=1,
                stdout="",
                stderr="",
            )
            assert _docker_running() is False

    def test_returns_false_when_docker_not_installed(self):
        with patch("forge.docker_manager.subprocess.run", side_effect=FileNotFoundError):
            assert _docker_running() is False

    def test_returns_false_on_timeout(self):
        with patch(
            "forge.docker_manager.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker info", timeout=10),
        ):
            assert _docker_running() is False


# -- boot ---------------------------------------------------------------------


class TestBoot:
    def test_no_compose_file(self, tmp_path, capsys):
        boot(tmp_path)
        assert "not found" in capsys.readouterr().out

    def test_docker_not_running(self, tmp_path, capsys):
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        with patch("forge.docker_manager._docker_running", return_value=False):
            boot(tmp_path)
        out = capsys.readouterr().out
        assert "Docker is not running" in out

    def test_successful_boot(self, tmp_path, capsys):
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        with (
            patch("forge.docker_manager._docker_running", return_value=True),
            patch("forge.docker_manager.subprocess.run") as mock_run,
        ):
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="",
                stderr="",
            )
            boot(tmp_path)
        out = capsys.readouterr().out
        assert "Starting Docker Compose" in out

    def test_compose_failure_calls_teardown(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        with (
            patch("forge.docker_manager._docker_running", return_value=True),
            patch(
                "forge.docker_manager.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "docker compose"),
            ),
            patch("forge.docker_manager.teardown") as mock_teardown,
            pytest.raises(SystemExit),
        ):
            boot(tmp_path)
        mock_teardown.assert_called_once_with(tmp_path)

    def test_keyboard_interrupt_calls_teardown(self, tmp_path):
        (tmp_path / "docker-compose.yml").write_text("version: '3'")
        with (
            patch("forge.docker_manager._docker_running", return_value=True),
            patch(
                "forge.docker_manager.subprocess.run",
                side_effect=KeyboardInterrupt,
            ),
            patch("forge.docker_manager.teardown") as mock_teardown,
        ):
            boot(tmp_path)
        mock_teardown.assert_called_once_with(tmp_path)


# -- teardown -----------------------------------------------------------------


class TestTeardown:
    def test_runs_compose_down(self, tmp_path, capsys):
        with patch("forge.docker_manager.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="",
                stderr="",
            )
            teardown(tmp_path)

        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert cmd == ["docker", "compose", "down", "--volumes", "--remove-orphans"]
        assert "stopped and cleaned up" in capsys.readouterr().out

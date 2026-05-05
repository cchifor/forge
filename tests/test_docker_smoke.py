"""Docker smoke tests -- validates generated compose files are valid."""

import shutil
import subprocess

import pytest

from forge.config import BackendConfig, FrontendConfig, FrontendFramework, ProjectConfig
from forge.generator import generate

# Skip if docker is not available
docker_available = shutil.which("docker") is not None
pytestmark = pytest.mark.skipif(not docker_available, reason="Docker not available")


class TestDockerComposeConfig:
    def test_backend_only_compose_is_valid(self, tmp_path):
        """Generated backend-only docker-compose.yml passes config validation."""
        config = ProjectConfig(
            project_name="smoke-test",
            output_dir=str(tmp_path),
            backends=[BackendConfig(project_name="smoke-test", server_port=5000)],
        )
        project_root = generate(config, quiet=True)
        result = subprocess.run(
            ["docker", "compose", "config", "--quiet"],
            cwd=str(project_root),
            capture_output=True,
            timeout=120,
        )
        assert result.returncode == 0, f"docker compose config failed: {result.stderr.decode()}"

    def test_fullstack_compose_is_valid(self, tmp_path):
        """Generated full-stack docker-compose.yml passes config validation."""
        config = ProjectConfig(
            project_name="smoke-test",
            output_dir=str(tmp_path),
            backends=[BackendConfig(project_name="smoke-test", server_port=5000)],
            frontend=FrontendConfig(
                framework=FrontendFramework.VUE,
                project_name="smoke-test",
                server_port=5173,
                features=["items"],
            ),
        )
        project_root = generate(config, quiet=True)
        result = subprocess.run(
            ["docker", "compose", "config", "--quiet"],
            cwd=str(project_root),
            capture_output=True,
            timeout=120,
        )
        assert result.returncode == 0, f"docker compose config failed: {result.stderr.decode()}"

    def test_keycloak_compose_is_valid(self, tmp_path):
        """Generated compose with Keycloak passes config validation."""
        config = ProjectConfig(
            project_name="smoke-test",
            output_dir=str(tmp_path),
            backends=[BackendConfig(project_name="smoke-test", server_port=5000)],
            include_keycloak=True,
            keycloak_port=8080,
        )
        project_root = generate(config, quiet=True)
        result = subprocess.run(
            ["docker", "compose", "config", "--quiet"],
            cwd=str(project_root),
            capture_output=True,
            timeout=120,
        )
        assert result.returncode == 0

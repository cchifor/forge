"""Tests for forge.docker_manager compose rendering."""

import yaml
import pytest

from forge.config import (
    BackendConfig,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.docker_manager import (
    render_compose,
    render_frontend_dockerfile,
    render_nginx_conf,
)


def _make_config(
    framework=FrontendFramework.VUE,
    include_keycloak=False,
    has_frontend=True,
):
    bc = BackendConfig(project_name="Test App", server_port=5000)
    fc = None
    if has_frontend:
        fc = FrontendConfig(
            framework=framework,
            project_name="Test App",
            server_port=5173,
            keycloak_url="http://localhost:8080",
            keycloak_realm="master",
            keycloak_client_id="test-app",
        )
    return ProjectConfig(
        project_name="Test App",
        backend=bc,
        frontend=fc,
        include_keycloak=include_keycloak,
        keycloak_port=8080,
    )


class TestRenderCompose:
    def test_backend_only(self, tmp_path):
        config = _make_config(has_frontend=False)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert "backend" in data["services"]
        assert "postgres" in data["services"]
        assert "frontend" not in data["services"]

    def test_backend_with_vue(self, tmp_path):
        config = _make_config(framework=FrontendFramework.VUE)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert "frontend" in data["services"]
        assert data["services"]["frontend"]["ports"] == ["5173:80"]

    def test_flutter_included_in_compose(self, tmp_path):
        config = _make_config(framework=FrontendFramework.FLUTTER)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert "frontend" in data["services"]
        assert data["services"]["frontend"]["ports"] == ["5173:80"]

    def test_frontend_no_vite_env_vars(self, tmp_path):
        config = _make_config(framework=FrontendFramework.VUE)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        frontend = data["services"]["frontend"]
        assert "environment" not in frontend

    def test_keycloak_included(self, tmp_path):
        config = _make_config(include_keycloak=True)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert "keycloak" in data["services"]
        assert data["services"]["keycloak"]["ports"] == ["8080:8080"]
        env = data["services"]["backend"]["environment"]
        assert env["APP__SECURITY__AUTH__ENABLED"] == "true"

    def test_keycloak_excluded(self, tmp_path):
        config = _make_config(include_keycloak=False)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert "keycloak" not in data["services"]
        env = data["services"]["backend"]["environment"]
        assert env["APP__SECURITY__AUTH__ENABLED"] == "false"

    def test_pgadmin_in_tools_profile(self, tmp_path):
        config = _make_config(has_frontend=False)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert data["services"]["pgadmin"]["profiles"] == ["tools"]

    def test_network_defined(self, tmp_path):
        config = _make_config(has_frontend=False)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert "app-network" in data["networks"]

    def test_backend_ports(self, tmp_path):
        config = _make_config(has_frontend=False)
        config.backend.server_port = 8000
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        assert data["services"]["backend"]["ports"] == ["8000:8000"]

    def test_postgres_healthcheck(self, tmp_path):
        config = _make_config(has_frontend=False)
        compose_path = render_compose(config, tmp_path)
        data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

        pg = data["services"]["postgres"]
        assert "healthcheck" in pg
        assert pg["healthcheck"]["retries"] == 5


class TestRenderFrontendDockerfile:
    def test_two_stage_build(self, tmp_path):
        config = _make_config(framework=FrontendFramework.VUE)
        path = render_frontend_dockerfile(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "FROM node:22-slim AS builder" in content
        assert "FROM nginx:alpine" in content
        assert "run build" in content

    def test_vue_copies_dist(self, tmp_path):
        config = _make_config(framework=FrontendFramework.VUE)
        path = render_frontend_dockerfile(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "/app/dist" in content

    def test_svelte_copies_build(self, tmp_path):
        config = _make_config(framework=FrontendFramework.SVELTE)
        path = render_frontend_dockerfile(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "/app/build" in content

    def test_pnpm_dockerfile(self, tmp_path):
        config = _make_config(framework=FrontendFramework.SVELTE)
        config.frontend.package_manager = "pnpm"
        path = render_frontend_dockerfile(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "corepack enable" in content
        assert "pnpm-lock.yaml" in content

    def test_bun_dockerfile(self, tmp_path):
        config = _make_config(framework=FrontendFramework.SVELTE)
        config.frontend.package_manager = "bun"
        path = render_frontend_dockerfile(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "npm install -g bun" in content
        assert "bun.lockb" in content

    def test_flutter_dockerfile(self, tmp_path):
        config = _make_config(framework=FrontendFramework.FLUTTER)
        path = render_frontend_dockerfile(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "cirruslabs/flutter" in content
        assert "flutter build web" in content
        assert "FROM nginx:alpine" in content
        assert "build/web" in content

    def test_nginx_conf_copied(self, tmp_path):
        """Dockerfile references nginx.conf for all frameworks."""
        for fw in (FrontendFramework.VUE, FrontendFramework.SVELTE, FrontendFramework.FLUTTER):
            config = _make_config(framework=fw)
            path = render_frontend_dockerfile(config, tmp_path)
            content = path.read_text(encoding="utf-8")
            assert "nginx.conf" in content


class TestRenderNginxConf:
    def test_renders_proxy(self, tmp_path):
        config = _make_config()
        path = render_nginx_conf(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "proxy_pass http://backend:5000/api/" in content
        assert "try_files" in content

    def test_custom_backend_port(self, tmp_path):
        config = _make_config()
        config.backend.server_port = 8000
        path = render_nginx_conf(config, tmp_path)
        content = path.read_text(encoding="utf-8")

        assert "proxy_pass http://backend:8000/api/" in content

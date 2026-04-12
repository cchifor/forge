"""Tests for forge.variable_mapper."""

import pytest

from forge.config import (
    BackendConfig,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.variable_mapper import (
    backend_context,
    e2e_context,
    flutter_context,
    frontend_context,
    svelte_context,
    vue_context,
)


def _make_config(framework=FrontendFramework.VUE, **fe_overrides):
    bc = BackendConfig(
        project_name="Test App",
        description="A test service",
        features=["items", "orders"],
        python_version="3.13",
        server_port=5000,
    )
    fe_defaults = dict(
        framework=framework,
        project_name="Test App",
        description="A test frontend",
        author_name="Dev",
        package_manager="pnpm",
        include_auth=True,
        include_chat=True,
        include_openapi=False,
        server_port=5173,
        keycloak_url="http://localhost:8080",
        keycloak_realm="myrealm",
        keycloak_client_id="test-app",
        default_color_scheme="teal",
        org_name="com.test",
    )
    fe_defaults.update(fe_overrides)
    fc = FrontendConfig(**fe_defaults)
    return ProjectConfig(
        project_name="Test App",
        backends=[bc],
        frontend=fc,
        include_keycloak=True,
        keycloak_port=8080,
    )


class TestBackendContext:
    def test_maps_all_fields(self):
        config = _make_config()
        ctx = backend_context(config.backend)
        assert ctx["project_name"] == "backend"
        assert ctx["project_description"] == "A test service"
        assert ctx["server_port"] == 5000
        assert isinstance(ctx["server_port"], int)
        assert ctx["db_name"] == "backend"
        assert ctx["python_version"] == "3.13"

    def test_minimal_schema(self):
        """Backend context should have the expected fields from copier.yml."""
        config = _make_config()
        ctx = backend_context(config.backend)
        assert set(ctx.keys()) == {
            "project_name", "project_description", "server_port",
            "db_name", "python_version", "entity_plural",
        }


class TestVueContext:
    def test_maps_all_fields(self):
        config = _make_config(framework=FrontendFramework.VUE)
        ctx = vue_context(config)
        assert ctx["project_name"] == "Test App"
        assert ctx["project_slug"] == "frontend"
        assert ctx["features"] == "items, orders"
        assert ctx["package_manager"] == "pnpm"
        assert ctx["include_auth"] is True
        assert ctx["include_chat"] is True
        assert ctx["include_openapi"] is False
        assert ctx["api_proxy_target"] == "http://backend:5000"
        assert ctx["server_port"] == 5173
        assert isinstance(ctx["server_port"], int)
        assert ctx["keycloak_realm"] == "myrealm"
        assert ctx["default_color_scheme"] == "teal"

    def test_booleans_are_native(self):
        config = _make_config(framework=FrontendFramework.VUE, include_auth=False)
        ctx = vue_context(config)
        assert ctx["include_auth"] is False
        assert not isinstance(ctx["include_auth"], str)

    def test_proxy_target_uses_docker_dns(self):
        config = _make_config(framework=FrontendFramework.VUE)
        config.backend.server_port = 8000
        ctx = vue_context(config)
        assert ctx["api_proxy_target"] == "http://backend:8000"


class TestSvelteContext:
    def test_maps_all_fields(self):
        config = _make_config(framework=FrontendFramework.SVELTE)
        ctx = svelte_context(config)
        assert ctx["project_name"] == "Test App"
        assert ctx["api_base_url"] == "http://backend:5000"
        assert ctx["include_auth"] is True
        assert ctx["include_chat"] is True
        assert isinstance(ctx["server_port"], int)
        assert "include_openapi" not in ctx
        assert "default_color_scheme" not in ctx

    def test_wrong_framework_raises(self):
        config = _make_config(framework=FrontendFramework.VUE)
        with pytest.raises(ValueError):
            svelte_context(config)


class TestFlutterContext:
    def test_maps_all_fields(self):
        config = _make_config(framework=FrontendFramework.FLUTTER)
        ctx = flutter_context(config)
        assert ctx["project_name"] == "Test App"
        assert ctx["org_name"] == "com.test"
        assert ctx["include_auth"] is True
        assert ctx["include_openapi"] is False
        assert ctx["api_base_url"] == "http://localhost:5000"
        assert "package_manager" not in ctx
        assert "default_color_scheme" not in ctx


class TestFrontendContextDispatch:
    def test_dispatches_vue(self):
        config = _make_config(framework=FrontendFramework.VUE)
        ctx = frontend_context(config)
        assert "default_color_scheme" in ctx

    def test_dispatches_svelte(self):
        config = _make_config(framework=FrontendFramework.SVELTE)
        ctx = frontend_context(config)
        assert "default_color_scheme" not in ctx

    def test_no_frontend_raises(self):
        config = _make_config()
        config.frontend = None
        with pytest.raises(ValueError):
            frontend_context(config)


class TestE2eContext:
    def test_maps_all_fields(self):
        config = _make_config(framework=FrontendFramework.VUE)
        ctx = e2e_context(config)
        assert ctx["project_name"] == "Test App"
        assert ctx["features"] == "items, orders"
        assert ctx["include_auth"] is True
        assert ctx["base_url"] == "http://localhost:5173"
        assert ctx["frontend_framework"] == "vue"
        assert ctx["keycloak_url"] == "http://localhost:8080"
        assert ctx["keycloak_realm"] == "myrealm"
        assert ctx["keycloak_client_id"] == "test-app"
        assert "backend_features" in ctx

    def test_no_auth(self):
        config = _make_config(framework=FrontendFramework.VUE)
        config.include_keycloak = False
        ctx = e2e_context(config)
        assert ctx["include_auth"] is False
        assert ctx["keycloak_url"] == ""
        assert ctx["keycloak_realm"] == ""
        assert ctx["keycloak_client_id"] == ""

    def test_svelte_framework(self):
        config = _make_config(framework=FrontendFramework.SVELTE)
        ctx = e2e_context(config)
        assert ctx["frontend_framework"] == "svelte"

    def test_multi_backend_features(self):
        config = _make_config(framework=FrontendFramework.VUE)
        config.backends.append(BackendConfig(
            name="orders-svc",
            features=["orders"],
            server_port=5001,
        ))
        ctx = e2e_context(config)
        import json
        bf = json.loads(ctx["backend_features"])
        assert "backend" in bf
        assert "orders-svc" in bf
        assert bf["orders-svc"]["port"] == 5001

"""Tests for headless mode config building."""

import json
import pytest
from argparse import Namespace
from pathlib import Path

from forge.cli import _build_config, _is_headless, _load_config_file
from forge.config import FrontendFramework


def _default_args(**overrides):
    """Create an args namespace with all defaults set to None."""
    defaults = dict(
        config=None, project_name=None, description=None, output_dir=".",
        backend_port=None, python_version=None, frontend=None, features=None,
        author_name=None, package_manager=None, frontend_port=None,
        color_scheme=None, org_name=None, include_auth=None, include_chat=None,
        include_openapi=None, keycloak_port=None, keycloak_realm=None,
        keycloak_client_id=None, yes=False, no_docker=False,
        quiet=False, json_output=False,
    )
    defaults.update(overrides)
    return Namespace(**defaults)


class TestIsHeadless:
    def test_no_args_is_interactive(self):
        assert not _is_headless(_default_args())

    def test_config_flag_is_headless(self):
        assert _is_headless(_default_args(config="stack.yaml"))

    def test_project_name_flag_is_headless(self):
        assert _is_headless(_default_args(project_name="test"))

    def test_yes_flag_is_headless(self):
        assert _is_headless(_default_args(yes=True))

    def test_frontend_flag_is_headless(self):
        assert _is_headless(_default_args(frontend="vue"))


class TestBuildConfig:
    def test_defaults_only(self):
        config = _build_config(_default_args(), {})
        assert config.project_name == "My Platform"
        assert config.backend.server_port == 5000
        assert config.frontend is None

    def test_from_config_dict(self):
        cfg = {
            "project_name": "my-shop",
            "backend": {"features": "products, orders"},
            "frontend": {"framework": "vue"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.project_name == "my-shop"
        assert config.frontend.framework == FrontendFramework.VUE
        assert config.backend.features == ["products", "orders"]
        assert config.all_features == ["products", "orders"]

    def test_cli_flags_override_config(self):
        cfg = {"project_name": "from-file"}
        args = _default_args(project_name="from-flag")
        config = _build_config(args, cfg)
        assert config.project_name == "from-flag"

    def test_backend_port_from_flag(self):
        args = _default_args(backend_port=8000)
        config = _build_config(args, {})
        assert config.backend.server_port == 8000

    def test_frontend_none(self):
        args = _default_args(frontend="none")
        config = _build_config(args, {})
        assert config.frontend is None

    def test_keycloak_from_config(self):
        cfg = {
            "frontend": {"framework": "vue", "include_auth": True},
            "keycloak": {"port": 9090, "realm": "dev", "client_id": "myapp"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.include_keycloak is True
        assert config.keycloak_port == 9090
        assert config.frontend.keycloak_realm == "dev"

    def test_no_auth_disables_keycloak(self):
        cfg = {"frontend": {"framework": "svelte", "include_auth": False}}
        config = _build_config(_default_args(), cfg)
        assert config.include_keycloak is False

    def test_features_flag_sets_backend_features(self):
        """--features CLI flag should set backend features, not frontend."""
        args = _default_args(features="products, orders", frontend="vue")
        config = _build_config(args, {})
        assert config.backend.features == ["products", "orders"]
        assert config.all_features == ["products", "orders"]

    def test_backend_features_from_config_file(self):
        """Single backend features from config file flow to all_features."""
        cfg = {
            "backend": {"features": "widgets, gadgets"},
            "frontend": {"framework": "svelte"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.backend.features == ["widgets", "gadgets"]
        assert config.all_features == ["widgets", "gadgets"]

    def test_multi_backend_features_aggregate(self):
        """Multi-backend features aggregate into all_features."""
        cfg = {
            "backends": [
                {"name": "svc-a", "language": "python", "features": ["items", "orders"]},
                {"name": "svc-b", "language": "node", "features": ["products"], "server_port": 5001},
            ],
            "frontend": {"framework": "vue"},
        }
        config = _build_config(_default_args(), cfg)
        assert config.all_features == ["items", "orders", "products"]

    def test_default_backend_features_when_none_specified(self):
        """Backend defaults to ['items'] when no features specified."""
        config = _build_config(_default_args(), {})
        assert config.backend.features == ["items"]


class TestLoadConfigFile:
    def test_json_file(self, tmp_path):
        f = tmp_path / "config.json"
        f.write_text(json.dumps({"project_name": "test"}))
        result = _load_config_file(str(f))
        assert result["project_name"] == "test"

    def test_yaml_file(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("project_name: test\n")
        result = _load_config_file(str(f))
        assert result["project_name"] == "test"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Config file not found"):
            _load_config_file(str(tmp_path / "nope.json"))

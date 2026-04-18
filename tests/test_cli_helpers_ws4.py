"""Tests for the helpers extracted in WS4: _normalize_features, _build_backends_from_cfg,
_build_frontend_from_cfg, _prompt_backend (smoke), and the validate() splits."""

from __future__ import annotations

import sys
from argparse import Namespace
from unittest.mock import patch

import pytest

from forge.cli import (
    _Resolver,
    _build_backends_from_cfg,
    _build_config,
    _build_frontend_from_cfg,
    _normalize_features,
    _prompt_backend,
)
from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendFramework,
    ProjectConfig,
)


# -- _normalize_features ------------------------------------------------------


class TestNormalizeFeatures:
    def test_none_returns_default(self) -> None:
        assert _normalize_features(None, default=["items"]) == ["items"]

    def test_none_no_default_returns_empty(self) -> None:
        assert _normalize_features(None) == []

    def test_list_input_stripped(self) -> None:
        assert _normalize_features(["foo", " bar ", "  "]) == ["foo", "bar"]

    def test_csv_string_input(self) -> None:
        assert _normalize_features("orders, customers ,  invoices") == [
            "orders",
            "customers",
            "invoices",
        ]

    def test_int_coerced_to_list(self) -> None:
        assert _normalize_features(["items", 42]) == ["items", "42"]


# -- _build_backends_from_cfg -------------------------------------------------


def _empty_args() -> Namespace:
    """Args namespace with all CLI flags set to None — config-file-only path."""
    return Namespace(
        project_name=None,
        description=None,
        output_dir=".",
        backend_language=None,
        backend_name=None,
        backend_port=None,
        python_version=None,
        node_version=None,
        rust_edition=None,
        features=None,
        frontend=None,
        author_name=None,
        package_manager=None,
        include_auth=None,
        include_chat=None,
        include_openapi=None,
        frontend_port=None,
        color_scheme=None,
        org_name=None,
        generate_e2e_tests=None,
        keycloak_port=None,
        keycloak_realm=None,
        keycloak_client_id=None,
        yes=True,
        no_docker=True,
        quiet=True,
        json_output=False,
        config=None,
    )


class TestBuildBackendsFromCfg:
    def test_multi_backend_list_from_cfg(self) -> None:
        cfg = {
            "backends": [
                {"name": "api", "language": "python", "features": ["items"]},
                {"name": "queue", "language": "node", "features": "tasks, jobs"},
                {"name": "core", "language": "rust"},
            ]
        }
        backends = _build_backends_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert [b.name for b in backends] == ["api", "queue", "core"]
        assert [b.language for b in backends] == [
            BackendLanguage.PYTHON,
            BackendLanguage.NODE,
            BackendLanguage.RUST,
        ]
        assert backends[0].features == ["items"]
        assert backends[1].features == ["tasks", "jobs"]
        # Default port offsets keep multi-backend collisions at bay by default.
        assert backends[0].server_port == 5000
        assert backends[1].server_port == 5001
        assert backends[2].server_port == 5002

    def test_invalid_backend_entry_skipped(self) -> None:
        cfg = {"backends": [{"name": "ok"}, "garbage", 42, {"name": "also-ok"}]}
        backends = _build_backends_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert [b.name for b in backends] == ["ok", "also-ok"]

    def test_falls_back_to_single_backend(self) -> None:
        cfg: dict = {}
        backends = _build_backends_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert len(backends) == 1
        assert backends[0].name == "backend"
        assert backends[0].language == BackendLanguage.PYTHON

    def test_single_backend_from_cfg_block(self) -> None:
        cfg = {"backend": {"name": "svc", "language": "rust"}}
        backends = _build_backends_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert len(backends) == 1
        assert backends[0].name == "svc"
        assert backends[0].language == BackendLanguage.RUST


# -- _build_frontend_from_cfg -------------------------------------------------


class TestBuildFrontendFromCfg:
    def test_no_frontend(self) -> None:
        cfg = {"frontend": {"framework": "none"}}
        fe, include_auth = _build_frontend_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert fe is None
        assert include_auth is False

    def test_vue_with_auth_default(self) -> None:
        cfg = {"frontend": {"framework": "vue"}}
        fe, include_auth = _build_frontend_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert fe is not None
        assert fe.framework == FrontendFramework.VUE
        assert include_auth is True
        assert fe.include_auth is True

    def test_svelte_explicit_no_auth(self) -> None:
        cfg = {"frontend": {"framework": "svelte", "include_auth": False}}
        fe, include_auth = _build_frontend_from_cfg(_Resolver(_empty_args(), cfg), "Proj", "desc")
        assert fe is not None
        assert fe.framework == FrontendFramework.SVELTE
        assert include_auth is False
        assert fe.include_auth is False


# -- _build_config orchestration ----------------------------------------------


class TestBuildConfig:
    def test_full_round_trip(self) -> None:
        cfg = {
            "project_name": "Acme",
            "backends": [{"name": "api", "language": "python"}],
            "frontend": {"framework": "vue"},
        }
        config = _build_config(_empty_args(), cfg)
        assert isinstance(config, ProjectConfig)
        assert config.project_name == "Acme"
        assert len(config.backends) == 1
        assert config.frontend is not None
        assert config.include_keycloak is True  # mirrors include_auth default


# -- ProjectConfig.validate() splits ------------------------------------------


class TestValidateSplits:
    def _make(self, **overrides) -> ProjectConfig:
        bc = BackendConfig(name="api", project_name="P", server_port=5000)
        defaults: dict = {
            "project_name": "P",
            "backends": [bc],
            "include_keycloak": False,
        }
        defaults.update(overrides)
        return ProjectConfig(**defaults)

    def test_duplicate_backend_names_caught(self) -> None:
        config = self._make(
            backends=[
                BackendConfig(name="api", project_name="P", server_port=5000),
                BackendConfig(name="api", project_name="P", server_port=5001),
            ],
        )
        with pytest.raises(ValueError, match="must be unique"):
            config.validate()

    def test_port_collision_caught(self) -> None:
        config = self._make(
            backends=[
                BackendConfig(name="a", project_name="P", server_port=5000),
                BackendConfig(name="b", project_name="P", server_port=5000),
            ],
        )
        with pytest.raises(ValueError, match="Port 5000"):
            config.validate()

    def test_postgres_port_collision_caught(self) -> None:
        config = self._make(
            backends=[BackendConfig(name="a", project_name="P", server_port=5432)],
        )
        with pytest.raises(ValueError, match="PostgreSQL"):
            config.validate()


# -- _prompt_backend (smoke; relies on questionary mocks) ---------------------


class TestPromptBackendSmoke:
    def test_python_path(self) -> None:
        with (
            patch("forge.cli._ask_text", side_effect=["api", "items"]),
            patch(
                "forge.cli._ask_select",
                side_effect=["Python (FastAPI)", "3.13"],
            ),
            patch("forge.cli._ask_port", return_value=5000),
        ):
            bc = _prompt_backend(0, "Proj", "desc", default_port=5000)
        assert bc.name == "api"
        assert bc.language == BackendLanguage.PYTHON
        assert bc.python_version == "3.13"
        assert bc.server_port == 5000
        assert bc.features == ["items"]

    def test_rust_path(self) -> None:
        with (
            patch("forge.cli._ask_text", side_effect=["core", "items"]),
            patch(
                "forge.cli._ask_select",
                side_effect=["Rust (Axum)", "2024"],
            ),
            patch("forge.cli._ask_port", return_value=5002),
        ):
            bc = _prompt_backend(2, "Proj", "desc", default_port=5002)
        assert bc.name == "core"
        assert bc.language == BackendLanguage.RUST
        assert bc.rust_edition == "2024"
        assert bc.server_port == 5002

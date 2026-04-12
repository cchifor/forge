"""Tests for forge.config validation."""

import pytest

from forge.config import (
    BackendConfig,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
    validate_features,
    validate_port,
)


# -- validate_port ------------------------------------------------------------

class TestValidatePort:
    def test_valid_ports(self):
        validate_port(1024, "test")
        validate_port(5000, "test")
        validate_port(65535, "test")

    def test_too_low(self):
        with pytest.raises(ValueError, match="must be between"):
            validate_port(80, "test")

    def test_too_high(self):
        with pytest.raises(ValueError, match="must be between"):
            validate_port(70000, "test")


# -- validate_features --------------------------------------------------------

class TestValidateFeatures:
    def test_valid_features(self):
        validate_features(["items", "orders", "products"])

    def test_empty_list(self):
        validate_features([])

    def test_invalid_start(self):
        with pytest.raises(ValueError, match="must be lowercase"):
            validate_features(["1items"])

    def test_uppercase(self):
        with pytest.raises(ValueError, match="must be lowercase"):
            validate_features(["Items"])

    def test_python_keyword(self):
        with pytest.raises(ValueError, match="Python keyword"):
            validate_features(["class"])

    def test_duplicate(self):
        with pytest.raises(ValueError, match="Duplicate"):
            validate_features(["items", "items"])


# -- BackendConfig ------------------------------------------------------------

class TestBackendConfig:
    def test_valid(self):
        bc = BackendConfig(project_name="Test")
        bc.validate()

    def test_invalid_port(self):
        bc = BackendConfig(project_name="Test", server_port=80)
        with pytest.raises(ValueError, match="must be between"):
            bc.validate()

    def test_defaults(self):
        bc = BackendConfig(project_name="Test")
        assert bc.description == "A microservice"
        assert bc.python_version == "3.13"
        assert bc.server_port == 5000


# -- FrontendConfig -----------------------------------------------------------

class TestFrontendConfig:
    def test_valid_vue(self):
        fc = FrontendConfig(
            framework=FrontendFramework.VUE,
            project_name="Test",
            package_manager="pnpm",
        )
        fc.validate()

    def test_invalid_package_manager(self):
        fc = FrontendConfig(
            framework=FrontendFramework.VUE,
            project_name="Test",
            package_manager="bun",
        )
        with pytest.raises(ValueError, match="not valid for vue"):
            fc.validate()

    def test_svelte_bun_valid(self):
        fc = FrontendConfig(
            framework=FrontendFramework.SVELTE,
            project_name="Test",
            package_manager="bun",
        )
        fc.validate()

    def test_none_skips_validation(self):
        fc = FrontendConfig(
            framework=FrontendFramework.NONE,
            project_name="Test",
            package_manager="invalid",
            server_port=1,
        )
        fc.validate()  # should not raise

    def test_reserved_feature(self):
        fc = FrontendConfig(
            framework=FrontendFramework.VUE,
            project_name="Test",
            features=["auth"],
        )
        with pytest.raises(ValueError, match="reserved"):
            fc.validate()


# -- ProjectConfig ------------------------------------------------------------

class TestProjectConfig:
    def _make_config(self, **overrides):
        defaults = dict(
            project_name="My Platform",
            backends=[BackendConfig(project_name="My Platform")],
            frontend=FrontendConfig(
                framework=FrontendFramework.VUE,
                project_name="My Platform",
            ),
        )
        defaults.update(overrides)
        return ProjectConfig(**defaults)

    def test_valid(self):
        cfg = self._make_config()
        cfg.validate()

    def test_port_collision(self):
        cfg = self._make_config(
            backends=[BackendConfig(project_name="Test", server_port=5173)],
            frontend=FrontendConfig(
                framework=FrontendFramework.VUE,
                project_name="Test",
                server_port=5173,
            ),
        )
        with pytest.raises(ValueError, match="used by both"):
            cfg.validate()

    def test_empty_name(self):
        cfg = self._make_config(project_name="  ")
        with pytest.raises(ValueError, match="cannot be empty"):
            cfg.validate()

    def test_slug_generation(self):
        cfg = self._make_config(project_name="My Cool Platform")
        assert cfg.project_slug == "my_cool_platform"
        assert cfg.backend_slug == "backend"
        assert cfg.frontend_slug == "frontend"

    def test_flutter_excluded_from_port_check(self):
        """Flutter doesn't use host ports in Docker, so no collision."""
        cfg = self._make_config(
            backends=[BackendConfig(project_name="Test", server_port=5000)],
            frontend=FrontendConfig(
                framework=FrontendFramework.FLUTTER,
                project_name="Test",
                server_port=5000,
            ),
        )
        cfg.validate()  # should not raise

    def test_all_features_deduplicates(self):
        """Multi-backend with overlapping features should deduplicate."""
        cfg = self._make_config(
            backends=[
                BackendConfig(project_name="Test", name="svc-a", features=["items", "orders"], server_port=5000),
                BackendConfig(project_name="Test", name="svc-b", features=["orders", "products"], server_port=5001),
            ],
        )
        assert cfg.all_features == ["items", "orders", "products"]

    def test_backend_reserved_feature_with_frontend(self):
        """Backend feature that conflicts with frontend reserved names should be rejected."""
        cfg = self._make_config(
            backends=[BackendConfig(project_name="Test", features=["auth"])],
        )
        with pytest.raises(ValueError, match="reserved"):
            cfg.validate()

    def test_backend_reserved_feature_without_frontend(self):
        """Backend reserved feature is fine when no frontend is configured."""
        cfg = self._make_config(
            backends=[BackendConfig(project_name="Test", features=["auth"])],
            frontend=None,
        )
        cfg.validate()  # should not raise

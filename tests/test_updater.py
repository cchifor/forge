"""Tests for forge/updater.py — the engine behind `forge update`."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)
from forge.errors import GeneratorError
from forge.features import FeatureConfig
from forge.forge_toml import read_forge_toml, write_forge_toml
from forge.updater import _infer_backends, update_project


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Build a stub forge-generated project without running Copier.

    Includes all markers the default-enabled features (correlation_id,
    pii_redaction, security_headers, rate_limit) target, so the resolver
    can expand defaults without the injector raising on missing files.
    """
    root = tmp_path / "proj"
    backend = root / "services" / "backend"
    (backend / "src" / "app" / "core").mkdir(parents=True)
    (backend / "src" / "app" / "middleware").mkdir(parents=True)
    (backend / "pyproject.toml").write_text(
        "[project]\nname=\"x\"\nversion=\"0.1\"\ndependencies = []\n",
        encoding="utf-8",
    )
    (backend / ".env.example").write_text("", encoding="utf-8")

    main_py = backend / "src" / "app" / "main.py"
    main_py.write_text(
        "\n".join(
            [
                "# FORGE:MIDDLEWARE_IMPORTS",
                "",
                "def create_app():",
                "    # FORGE:MIDDLEWARE_REGISTRATION",
                "    # FORGE:ROUTER_REGISTRATION",
                "    # FORGE:EXCEPTION_HANDLERS",
                "    # FORGE:APP_POST_CONFIGURE",
                "    return None",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lifecycle = backend / "src" / "app" / "core" / "lifecycle.py"
    lifecycle.write_text(
        "\n".join(
            [
                "def bootstrap():",
                "    # FORGE:LIFECYCLE_STARTUP",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


class TestInferBackends:
    def test_finds_python_backend(self, fake_project: Path) -> None:
        backends = _infer_backends(fake_project)
        assert len(backends) == 1
        assert backends[0].language == BackendLanguage.PYTHON
        assert backends[0].name == "backend"

    def test_ignores_dirs_without_marker(self, fake_project: Path) -> None:
        (fake_project / "services" / "rogue").mkdir()  # empty, no marker file
        backends = _infer_backends(fake_project)
        assert {b.name for b in backends} == {"backend"}

    def test_missing_services_dir_returns_empty(self, tmp_path: Path) -> None:
        assert _infer_backends(tmp_path) == []


class TestUpdateProject:
    def test_refuses_without_forge_toml(self, tmp_path: Path) -> None:
        with pytest.raises(GeneratorError, match="No forge.toml"):
            update_project(tmp_path)

    def test_restamps_version_and_feature_table(self, fake_project: Path) -> None:
        write_forge_toml(
            fake_project / "forge.toml",
            version="0.0.1",  # intentionally stale
            project_name="proj",
            templates={"python": "services/python-service-template"},
            features={
                "correlation_id": {"enabled": True, "options": {}},
            },
        )

        summary = update_project(fake_project, quiet=True)

        after = read_forge_toml(fake_project / "forge.toml")
        assert after.version != "0.0.1"  # re-stamped to current forge version
        assert "correlation_id" in after.features
        assert summary["backends"] == ["backend"]
        assert "correlation_id" in summary["features_applied"]

    def test_injection_is_idempotent_across_runs(self, fake_project: Path) -> None:
        """Calling update_project twice produces byte-identical files."""
        write_forge_toml(
            fake_project / "forge.toml",
            version="0.1.0",
            project_name="proj",
            templates={"python": "services/python-service-template"},
            features={"correlation_id": {"enabled": True, "options": {}}},
        )

        update_project(fake_project, quiet=True)
        main_py = fake_project / "services" / "backend" / "src" / "app" / "main.py"
        snapshot = main_py.read_text(encoding="utf-8")

        update_project(fake_project, quiet=True)
        assert main_py.read_text(encoding="utf-8") == snapshot

    def test_legacy_forge_toml_gets_upgraded(self, fake_project: Path) -> None:
        """A project written with the pre-B2.2 flat-list shape is readable
        and gets rewritten in the canonical shape on update.
        """
        manifest = fake_project / "forge.toml"
        manifest.write_text(
            "\n".join(
                [
                    "[forge]",
                    'version = "0.1.0"',
                    'project_name = "proj"',
                    "[forge.templates]",
                    'python = "services/python-service-template"',
                    "[forge.features]",
                    'enabled = ["correlation_id"]',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        assert read_forge_toml(manifest).legacy_features_format is True

        update_project(fake_project, quiet=True)

        upgraded = read_forge_toml(manifest)
        assert upgraded.legacy_features_format is False
        assert "correlation_id" in upgraded.features
        assert upgraded.features["correlation_id"]["enabled"] is True


class TestIntegrationAgainstGenerator:
    """End-to-end: use the real generator, then run update on the output."""

    def test_full_generate_then_update(self, tmp_path: Path, monkeypatch) -> None:
        from forge.generator import generate

        cfg = ProjectConfig(
            project_name="updatable",
            backends=(
                BackendConfig(
                    name="backend",
                    project_name="updatable",
                    language=BackendLanguage.PYTHON,
                ),
            ),
            frontend=FrontendConfig(
                framework=FrontendFramework.NONE, project_name="updatable"
            ),
            features={"rate_limit": FeatureConfig(enabled=True)},
            output_dir=str(tmp_path),
        )
        project_root = generate(cfg, quiet=True)

        main_py = project_root / "services" / "backend" / "src" / "app" / "main.py"
        before = main_py.read_text(encoding="utf-8")

        summary = update_project(project_root, quiet=True)

        after = main_py.read_text(encoding="utf-8")
        # Byte-identical: sentinels let re-injection be a no-op.
        assert before == after
        assert "rate_limit" in summary["features_applied"]

        # Cleanup (some Windows filesystems hold locks on the venv, so
        # shutil.rmtree may need ignore_errors).
        shutil.rmtree(project_root, ignore_errors=True)

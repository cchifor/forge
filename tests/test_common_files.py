"""Tests for the quality-signal common-files pass (4.4 of the 1.0 roadmap)."""

from __future__ import annotations

from pathlib import Path

from forge.common_files import COMMON_DIR, apply_common_files
from forge.config import BackendConfig, BackendLanguage, ProjectConfig


class TestApplyCommonFiles:
    def test_writes_editorconfig_gitignore_precommit(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            project_name="demo",
            backends=[
                BackendConfig(
                    name="api", project_name="demo", language=BackendLanguage.PYTHON
                )
            ],
            frontend=None,
        )
        apply_common_files(config, tmp_path)
        assert (tmp_path / ".editorconfig").is_file()
        assert (tmp_path / ".gitignore").is_file()
        assert (tmp_path / ".pre-commit-config.yaml").is_file()

    def test_writes_python_ci_workflow(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            project_name="demo",
            backends=[
                BackendConfig(
                    name="api", project_name="demo", language=BackendLanguage.PYTHON
                )
            ],
            frontend=None,
        )
        apply_common_files(config, tmp_path)
        ci = tmp_path / ".github" / "workflows" / "ci.yml"
        assert ci.is_file()
        assert "Python" in ci.read_text(encoding="utf-8")

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            project_name="demo",
            backends=[
                BackendConfig(
                    name="api", project_name="demo", language=BackendLanguage.PYTHON
                )
            ],
            frontend=None,
        )
        existing = tmp_path / ".editorconfig"
        existing.write_text("# user-owned editorconfig\n")
        apply_common_files(config, tmp_path)
        assert "user-owned" in existing.read_text()

    def test_node_backend_no_ci_yet(self, tmp_path: Path) -> None:
        """Only Python CI ships in 1.0.0a1; Node/Rust CI lands later."""
        config = ProjectConfig(
            project_name="demo",
            backends=[
                BackendConfig(
                    name="api", project_name="demo", language=BackendLanguage.NODE
                )
            ],
            frontend=None,
        )
        apply_common_files(config, tmp_path)
        assert not (tmp_path / ".github" / "workflows" / "ci.yml").exists()
        # But .editorconfig still lands.
        assert (tmp_path / ".editorconfig").is_file()

    def test_common_dir_has_expected_assets(self) -> None:
        """Sanity: every referenced asset exists on disk."""
        for name in ("editorconfig", "gitignore", "pre-commit-config.yaml", "ci_python.yml"):
            assert (COMMON_DIR / name).is_file(), f"missing {name}"

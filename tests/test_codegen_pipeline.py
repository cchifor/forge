"""Integration test for the codegen pipeline (Integration I1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.codegen.pipeline import run_codegen
from forge.config import (
    BackendConfig,
    BackendLanguage,
    FrontendConfig,
    FrontendFramework,
    ProjectConfig,
)


def _make_python_project(tmp_path: Path, frontend: FrontendFramework | None = None) -> tuple[ProjectConfig, Path]:
    project_root = tmp_path / "codegen_demo"
    project_root.mkdir()
    fe = None
    if frontend and frontend != FrontendFramework.NONE:
        fe = FrontendConfig(
            framework=frontend,
            project_name="codegen_demo",
            description="test",
            include_chat=True,
        )
    config = ProjectConfig(
        project_name="codegen_demo",
        backends=[
            BackendConfig(
                name="api",
                project_name="codegen_demo",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=fe,
    )
    return config, project_root


class TestUiProtocolEmission:
    def test_emits_pydantic_into_python_backend(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path)
        run_codegen(config, project_root)
        target = project_root / "services" / "api" / "src" / "app" / "domain" / "ui_protocol.py"
        assert target.is_file()
        body = target.read_text(encoding="utf-8")
        assert "class AgentState(BaseModel):" in body

    def test_emits_ts_into_vue_frontend(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path, FrontendFramework.VUE)
        run_codegen(config, project_root)
        target = (
            project_root
            / config.frontend_slug
            / "src"
            / "features"
            / "ai_chat"
            / "ui_protocol.gen.ts"
        )
        assert target.is_file()
        assert "export interface AgentState" in target.read_text(encoding="utf-8")

    def test_emits_dart_into_flutter_frontend(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path, FrontendFramework.FLUTTER)
        run_codegen(config, project_root)
        target = (
            project_root
            / config.frontend_slug
            / "lib"
            / "src"
            / "features"
            / "chat"
            / "domain"
            / "ui_protocol.gen.dart"
        )
        assert target.is_file()
        assert "class AgentState {" in target.read_text(encoding="utf-8")


class TestCanvasManifest:
    def test_writes_manifest_into_vue_public(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path, FrontendFramework.VUE)
        run_codegen(config, project_root)
        target = project_root / config.frontend_slug / "public" / "canvas.manifest.json"
        assert target.is_file()
        body = target.read_text(encoding="utf-8")
        assert "DataTable" in body
        assert "CodeViewer" in body

    def test_writes_manifest_into_flutter_assets(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path, FrontendFramework.FLUTTER)
        run_codegen(config, project_root)
        target = project_root / config.frontend_slug / "assets" / "canvas.manifest.json"
        assert target.is_file()

    def test_no_manifest_without_frontend(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path, FrontendFramework.NONE)
        run_codegen(config, project_root)
        # No frontend, no manifest.
        assert not any(project_root.rglob("canvas.manifest.json"))


class TestSharedEnums:
    def test_item_status_lands_in_python_backend(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path)
        run_codegen(config, project_root)
        target = (
            project_root / "services" / "api" / "src" / "app" / "domain" / "enums" / "item_status.py"
        )
        assert target.is_file()
        body = target.read_text(encoding="utf-8")
        assert "class ItemStatus(str, Enum):" in body

    def test_approval_mode_lands_in_vue_shared(self, tmp_path: Path) -> None:
        config, project_root = _make_python_project(tmp_path, FrontendFramework.VUE)
        run_codegen(config, project_root)
        target = (
            project_root
            / config.frontend_slug
            / "src"
            / "shared"
            / "enums"
            / "approval_mode.ts"
        )
        assert target.is_file()
        body = target.read_text(encoding="utf-8")
        assert "ApprovalMode" in body


class TestProvenance:
    def test_codegen_writes_provenance_records(self, tmp_path: Path) -> None:
        from forge.provenance import ProvenanceCollector  # noqa: PLC0415

        config, project_root = _make_python_project(tmp_path, FrontendFramework.VUE)
        collector = ProvenanceCollector(project_root=project_root)
        run_codegen(config, project_root, collector=collector)
        # Expect at least the UI-protocol emissions and canvas manifest
        # to have provenance entries.
        assert any(
            "ui_protocol" in key for key in collector.records
        ), f"no ui_protocol key in provenance: {list(collector.records)[:10]}"
        assert any("canvas.manifest" in key for key in collector.records)

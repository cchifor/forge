"""Tests for forge migrations (I9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.migrations import apply_migrations, discover_migrations


class TestDiscoverMigrations:
    def test_finds_registered_migrations(self) -> None:
        migrations = discover_migrations()
        names = {m.name for m in migrations}
        # Epic G (1.1.0-alpha.1) added rename-options alongside the original
        # three 0.x→1.0 codemods.
        assert names == {
            "ui-protocol",
            "entities",
            "adapters",
            "rename-options",
            "layer-modes",
        }

    def test_migrations_have_required_fields(self) -> None:
        for m in discover_migrations():
            assert m.name
            assert m.from_version
            assert m.to_version
            assert m.description
            assert callable(m.runner)


class TestMigrateUiProtocol:
    def test_renames_legacy_files(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_ui_protocol import run

        target = tmp_path / "apps" / "frontend" / "src" / "features" / "ai_chat" / "types.ts"
        target.parent.mkdir(parents=True)
        target.write_text("// legacy types\n", encoding="utf-8")

        report = run(tmp_path, dry_run=False, quiet=True)
        assert report.applied
        assert not target.exists()
        assert target.with_suffix(".ts.legacy").exists()

    def test_dry_run_does_not_mutate(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_ui_protocol import run

        target = tmp_path / "apps" / "frontend" / "src" / "features" / "ai_chat" / "types.ts"
        target.parent.mkdir(parents=True)
        target.write_text("// legacy\n", encoding="utf-8")

        report = run(tmp_path, dry_run=True, quiet=True)
        assert not report.applied
        assert target.exists()
        assert any("would rename" in c for c in report.changes)

    def test_empty_project_no_changes(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_ui_protocol import run

        report = run(tmp_path, dry_run=False, quiet=True)
        assert not report.applied
        assert report.skipped_reason == "no legacy files found"


class TestMigrateEntities:
    def test_suggests_yaml_for_detected_entities(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_entities import run

        entity_dir = tmp_path / "services" / "api" / "src" / "app" / "domain"
        entity_dir.mkdir(parents=True)
        (entity_dir / "order.py").write_text("# fake entity\n", encoding="utf-8")
        (entity_dir / "__init__.py").write_text("", encoding="utf-8")

        report = run(tmp_path, dry_run=False, quiet=True)
        suggestion = tmp_path / "domain" / "order.yaml.suggested"
        assert suggestion.exists()
        body = suggestion.read_text(encoding="utf-8")
        assert "name: Order" in body
        assert "plural: orders" in body


class TestMigrateAdapters:
    def test_suggests_port_when_legacy_rag_dir_present(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_adapters import run

        rag_dir = tmp_path / "services" / "api" / "src" / "app" / "rag"
        rag_dir.mkdir(parents=True)
        (rag_dir / "qdrant_client.py").write_text("# legacy\n", encoding="utf-8")

        report = run(tmp_path, dry_run=False, quiet=True)
        suggested = (
            tmp_path / "services" / "api" / "src" / "app" / "ports" / "vector_store.py.suggested"
        )
        assert suggested.exists()
        assert "VectorStorePort(Protocol)" in suggested.read_text(encoding="utf-8")


class TestApplyMigrations:
    def test_runs_all_when_no_filters(self, tmp_path: Path) -> None:
        reports = apply_migrations(tmp_path, quiet=True)
        names = {r.name for r in reports}
        assert names == {
            "ui-protocol",
            "entities",
            "adapters",
            "rename-options",
            "layer-modes",
        }

    def test_only_filter_limits_run(self, tmp_path: Path) -> None:
        reports = apply_migrations(tmp_path, only=["entities"], quiet=True)
        assert len(reports) == 1
        assert reports[0].name == "entities"

    def test_skip_filter_excludes(self, tmp_path: Path) -> None:
        reports = apply_migrations(tmp_path, skip=["entities"], quiet=True)
        names = {r.name for r in reports}
        assert "entities" not in names

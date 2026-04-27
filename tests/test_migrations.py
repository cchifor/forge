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
        # three 0.x→1.0 codemods. P0.1 (1.1.0-alpha.2) added adopt-baseline
        # for the merge-mode rollout.
        assert names == {
            "ui-protocol",
            "entities",
            "adapters",
            "rename-options",
            "layer-modes",
            "adopt-baseline",
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
            "adopt-baseline",
        }

    def test_only_filter_limits_run(self, tmp_path: Path) -> None:
        reports = apply_migrations(tmp_path, only=["entities"], quiet=True)
        assert len(reports) == 1
        assert reports[0].name == "entities"

    def test_skip_filter_excludes(self, tmp_path: Path) -> None:
        reports = apply_migrations(tmp_path, skip=["entities"], quiet=True)
        names = {r.name for r in reports}
        assert "entities" not in names


class TestMigrateAdoptBaseline:
    """P0.1 — adopt-baseline codemod."""

    def _seed_manifest(self, project_root: Path) -> None:
        from forge.forge_toml import write_forge_toml  # noqa: PLC0415

        project_root.mkdir(exist_ok=True)
        write_forge_toml(
            project_root / "forge.toml",
            version="1.0.0",
            project_name="adopt-test",
            templates={"python": "services/python-service-template"},
            options={},
        )

    def test_stamps_files_under_source_roots(self, tmp_path: Path) -> None:
        from forge.forge_toml import read_forge_toml  # noqa: PLC0415
        from forge.merge import sha256_of_file  # noqa: PLC0415
        from forge.migrations.migrate_adopt_baseline import run  # noqa: PLC0415

        self._seed_manifest(tmp_path)
        target = tmp_path / "services" / "backend" / "src" / "app" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("def app(): pass\n", encoding="utf-8")

        report = run(tmp_path, dry_run=False, quiet=True)
        assert report.applied
        assert any("services/backend/src/app/main.py" in c for c in report.changes)

        data = read_forge_toml(tmp_path / "forge.toml")
        rel = "services/backend/src/app/main.py"
        assert rel in data.provenance
        assert data.provenance[rel]["origin"] == "base-template"
        assert data.provenance[rel]["sha256"] == sha256_of_file(target)

    def test_skips_node_modules_and_caches(self, tmp_path: Path) -> None:
        from forge.forge_toml import read_forge_toml  # noqa: PLC0415
        from forge.migrations.migrate_adopt_baseline import run  # noqa: PLC0415

        self._seed_manifest(tmp_path)
        # Files under skip-listed dirs should NOT be stamped.
        skipped = tmp_path / "apps" / "frontend" / "node_modules" / "lib" / "x.js"
        skipped.parent.mkdir(parents=True)
        skipped.write_text("module.exports = {};\n", encoding="utf-8")

        # ... while a sibling under a real source root SHOULD be stamped.
        kept = tmp_path / "apps" / "frontend" / "src" / "main.ts"
        kept.parent.mkdir(parents=True)
        kept.write_text("export {};\n", encoding="utf-8")

        run(tmp_path, dry_run=False, quiet=True)
        data = read_forge_toml(tmp_path / "forge.toml")
        assert "apps/frontend/src/main.ts" in data.provenance
        assert "apps/frontend/node_modules/lib/x.js" not in data.provenance

    def test_does_not_overwrite_existing_records(self, tmp_path: Path) -> None:
        from forge.forge_toml import read_forge_toml, write_forge_toml  # noqa: PLC0415
        from forge.migrations.migrate_adopt_baseline import run  # noqa: PLC0415

        self._seed_manifest(tmp_path)
        target = tmp_path / "services" / "backend" / "src" / "app" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("def app(): pass\n", encoding="utf-8")

        # Pre-existing record — codemod must not clobber.
        write_forge_toml(
            tmp_path / "forge.toml",
            version="1.0.0",
            project_name="adopt-test",
            templates={"python": "services/python-service-template"},
            options={},
            provenance={
                "services/backend/src/app/main.py": {
                    "origin": "fragment",
                    "sha256": "deadbeef" * 8,  # deliberately wrong
                    "fragment_name": "rate_limit",
                }
            },
        )

        run(tmp_path, dry_run=False, quiet=True)
        data = read_forge_toml(tmp_path / "forge.toml")
        rec = data.provenance["services/backend/src/app/main.py"]
        # Record preserved as-is — even the wrong SHA. Operator's manual
        # records win over the bulk codemod.
        assert rec["origin"] == "fragment"
        assert rec["sha256"] == "deadbeef" * 8
        assert rec["fragment_name"] == "rate_limit"

    def test_dry_run_reports_without_writing(self, tmp_path: Path) -> None:
        from forge.forge_toml import read_forge_toml  # noqa: PLC0415
        from forge.migrations.migrate_adopt_baseline import run  # noqa: PLC0415

        self._seed_manifest(tmp_path)
        target = tmp_path / "services" / "backend" / "src" / "app" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("def app(): pass\n", encoding="utf-8")

        report = run(tmp_path, dry_run=True, quiet=True)
        assert report.applied is False
        assert report.changes  # would-have-stamped paths are reported
        # Manifest unchanged.
        data = read_forge_toml(tmp_path / "forge.toml")
        assert "services/backend/src/app/main.py" not in data.provenance

    def test_idempotent_when_already_stamped(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_adopt_baseline import run  # noqa: PLC0415

        self._seed_manifest(tmp_path)
        target = tmp_path / "services" / "backend" / "src" / "app" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("def app(): pass\n", encoding="utf-8")

        first = run(tmp_path, dry_run=False, quiet=True)
        assert first.applied
        # Second pass: every file already has a record, so no-op.
        second = run(tmp_path, dry_run=False, quiet=True)
        assert second.applied is False
        assert "already has a provenance record" in (second.skipped_reason or "")

    def test_no_manifest_skips(self, tmp_path: Path) -> None:
        from forge.migrations.migrate_adopt_baseline import run  # noqa: PLC0415

        report = run(tmp_path, dry_run=False, quiet=True)
        assert report.applied is False
        assert "No forge.toml" in (report.skipped_reason or "")

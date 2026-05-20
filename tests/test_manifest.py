"""Tests for ``forge.sync.manifest`` — read/write round trips + v3→v4 inference.

The schema is intentionally additive: every prior version's manifests
must keep loading, and the read path must reconstruct the v4
``[forge.frontend]`` table from on-disk inference when an older
manifest is encountered (so Initiative #3's ``forge --update`` path
works without a forced migration step). These tests pin both
directions:

* Positive: v4 round trips preserve the frontend record.
* Negative-ish: a v3 manifest (no ``[forge.frontend]``) loads via the
  templates-table fallback OR the on-disk ``apps/<slug>/`` scan, and a
  malformed v3 with neither still loads with an empty frontend
  (rather than raising).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from forge.sync.manifest import (
    CURRENT_SCHEMA_VERSION,
    ForgeFrontendData,
    read_forge_toml,
    write_forge_toml,
)


def _write_v3_manifest(path: Path, *, with_frontend_template: bool = False) -> None:
    """Stamp a hand-rolled v3 manifest, optionally listing a frontend template."""
    extra = "vue = \"apps/vue-frontend-template\"\n" if with_frontend_template else ""
    path.write_text(
        dedent(
            f"""
            # Hand-rolled v3 manifest (pre-Initiative-#3, no [forge.frontend]).
            [forge]
            schema_version = 3
            version = "1.2.0"
            project_name = "legacy"

            [forge.templates]
            python = "services/python-service-template"
            {extra}
            [forge.template_versions]
            python = "0.6.1"

            [forge.options]

            [forge.option_origins]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


class TestSchemaVersionDefaults:
    def test_current_schema_version_is_four(self) -> None:
        # Bumping CURRENT_SCHEMA_VERSION needs a paired
        # migrate_provenance-style codemod; pin the constant so changes
        # land via an obvious test failure rather than a silent diff.
        assert CURRENT_SCHEMA_VERSION == 4


class TestV4RoundTrip:
    def test_frontend_round_trip_preserves_framework_and_app_dir(
        self, tmp_path: Path
    ) -> None:
        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.3.0",
            project_name="acme",
            templates={"python": "services/python-service-template"},
            options={},
            frontend=ForgeFrontendData(framework="vue", app_dir="apps/frontend"),
        )
        data = read_forge_toml(manifest)
        assert data.schema_version == 4
        assert data.frontend.framework == "vue"
        assert data.frontend.app_dir == "apps/frontend"

    def test_writer_omits_table_when_framework_blank(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.3.0",
            project_name="acme",
            templates={"python": "services/python-service-template"},
            options={},
            frontend=ForgeFrontendData(),  # empty record
        )
        text = manifest.read_text(encoding="utf-8")
        assert "[forge.frontend]" not in text

    def test_writer_omits_table_when_frontend_is_none(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        write_forge_toml(
            manifest,
            version="1.3.0",
            project_name="acme",
            templates={"python": "services/python-service-template"},
            options={},
            frontend=None,
        )
        text = manifest.read_text(encoding="utf-8")
        assert "[forge.frontend]" not in text


class TestV3InferenceFallback:
    """v3 manifests reconstruct [forge.frontend] from ``[forge.templates]``."""

    def test_templates_table_wins_over_disk_scan(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        _write_v3_manifest(manifest, with_frontend_template=True)
        data = read_forge_toml(manifest)
        assert data.schema_version == 3
        # Templates table referenced vue -> infer vue, default app_dir slot.
        assert data.frontend.framework == "vue"
        assert data.frontend.app_dir == "apps/frontend"

    def test_on_disk_scan_finds_vue_via_package_json(self, tmp_path: Path) -> None:
        _write_v3_manifest(tmp_path / "forge.toml", with_frontend_template=False)
        app = tmp_path / "apps" / "frontend"
        app.mkdir(parents=True)
        (app / "package.json").write_text(
            '{"name": "f", "dependencies": {"vue": "^3.5.0"}}\n',
            encoding="utf-8",
        )
        data = read_forge_toml(tmp_path / "forge.toml")
        assert data.frontend.framework == "vue"
        assert data.frontend.app_dir == "apps/frontend"

    def test_on_disk_scan_finds_svelte_via_package_json(self, tmp_path: Path) -> None:
        _write_v3_manifest(tmp_path / "forge.toml", with_frontend_template=False)
        app = tmp_path / "apps" / "frontend"
        app.mkdir(parents=True)
        (app / "package.json").write_text(
            '{"name": "f", "dependencies": {"svelte": "^5.0.0"}}\n',
            encoding="utf-8",
        )
        data = read_forge_toml(tmp_path / "forge.toml")
        assert data.frontend.framework == "svelte"
        assert data.frontend.app_dir == "apps/frontend"

    def test_on_disk_scan_finds_flutter_via_pubspec(self, tmp_path: Path) -> None:
        _write_v3_manifest(tmp_path / "forge.toml", with_frontend_template=False)
        app = tmp_path / "apps" / "flutter_app"
        app.mkdir(parents=True)
        (app / "pubspec.yaml").write_text("name: flutter_app\n", encoding="utf-8")
        data = read_forge_toml(tmp_path / "forge.toml")
        assert data.frontend.framework == "flutter"
        assert data.frontend.app_dir == "apps/flutter_app"

    def test_missing_frontend_yields_empty_record(self, tmp_path: Path) -> None:
        """Backend-only v3 manifest: no apps/, no frontend in templates."""
        _write_v3_manifest(tmp_path / "forge.toml", with_frontend_template=False)
        data = read_forge_toml(tmp_path / "forge.toml")
        assert data.frontend.framework == ""
        assert data.frontend.app_dir == ""

    def test_malformed_package_json_falls_through(self, tmp_path: Path) -> None:
        """A corrupt package.json must not raise — best-effort means empty record."""
        _write_v3_manifest(tmp_path / "forge.toml", with_frontend_template=False)
        app = tmp_path / "apps" / "frontend"
        app.mkdir(parents=True)
        # Truncated mid-key; json.loads will raise, the inference walks past.
        (app / "package.json").write_text('{"name": "f", "dep', encoding="utf-8")
        data = read_forge_toml(tmp_path / "forge.toml")
        # No framework derivable; the apps dir was found but no
        # recognisable marker matched, so framework collapses to "".
        assert data.frontend.framework == ""


class TestV4MissingTableTriggersInference:
    """v4 manifests where the writer omitted the table fall back to inference.

    This covers the ``--reapply-baseline`` / ``--accept-harvested`` /
    ``--remove-fragment`` paths that re-write the manifest at the
    current schema version without tracking frontend metadata. The
    read path treats "table missing or empty" as a v3 inference
    trigger, so those paths don't lose the frontend record across
    a round trip when the project layer is discoverable on disk.
    """

    def test_v4_without_frontend_table_infers_from_disk(self, tmp_path: Path) -> None:
        manifest = tmp_path / "forge.toml"
        # write_forge_toml with frontend=None stamps schema v4 but omits
        # the [forge.frontend] table — mirrors what reapply_baseline
        # does today.
        write_forge_toml(
            manifest,
            version="1.3.0",
            project_name="acme",
            templates={"python": "services/python-service-template"},
            options={},
            frontend=None,
        )
        app = tmp_path / "apps" / "frontend"
        app.mkdir(parents=True)
        (app / "package.json").write_text(
            '{"name": "f", "dependencies": {"vue": "^3.5.0"}}\n',
            encoding="utf-8",
        )
        data = read_forge_toml(manifest)
        assert data.schema_version == CURRENT_SCHEMA_VERSION
        # Inference filled it in from disk even though the manifest is v4.
        assert data.frontend.framework == "vue"


class TestForgeFrontendDataDefaults:
    def test_default_is_empty(self) -> None:
        fe = ForgeFrontendData()
        assert fe.framework == ""
        assert fe.app_dir == ""

    def test_frozen_dataclass(self) -> None:
        fe = ForgeFrontendData(framework="vue", app_dir="apps/frontend")
        try:
            fe.framework = "svelte"  # type: ignore[misc]
        except (AttributeError, Exception):  # noqa: BLE001
            return
        # Reached when assignment didn't raise — frozen dataclass should
        # have raised.
        raise AssertionError("ForgeFrontendData must be frozen")

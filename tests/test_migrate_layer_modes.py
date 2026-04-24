"""Phase C completion — ``migrate_layer_modes`` roundtrip tests.

Mirrors the pattern in ``migrate_rename_options.py:85`` — rewrite
legacy paths to canonical, re-run, second pass is a no-op. Covers
three file surfaces: ``forge.toml`` (tomlkit), ``.yaml`` (ruamel/
pyyaml), ``.json`` (stdlib).
"""

from __future__ import annotations

import json
from pathlib import Path

from forge.migrations.base import discover_migrations
from forge.migrations.migrate_layer_modes import run as run_layer_modes


# -- Helpers -----------------------------------------------------------------


def _make_forge_toml(root: Path, options: dict[str, str]) -> Path:
    lines = ["[forge]", "version = \"1.1.0\"", "", "[forge.options]"]
    for k, v in options.items():
        lines.append(f'"{k}" = "{v}"')
    path = root / "forge.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# -- Registration ------------------------------------------------------------


class TestMigrationDiscovery:
    def test_layer_modes_is_registered(self):
        names = {m.name for m in discover_migrations()}
        assert "layer-modes" in names

    def test_layer_modes_has_sensible_version_window(self):
        m = next(m for m in discover_migrations() if m.name == "layer-modes")
        assert m.from_version == "1.1.0"
        assert m.to_version == "1.2.0"


# -- forge.toml roundtrip ----------------------------------------------------


class TestTomlRoundtrip:
    def test_rewrite_happens(self, tmp_path: Path):
        _make_forge_toml(tmp_path, {"frontend.api_target_url": "https://x.example.com"})
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert report.applied is True
        assert any("frontend.api_target_url" in c for c in report.changes)
        body = (tmp_path / "forge.toml").read_text(encoding="utf-8")
        assert "frontend.api_target.url" in body
        assert "frontend.api_target_url" not in body

    def test_second_pass_is_noop(self, tmp_path: Path):
        _make_forge_toml(tmp_path, {"frontend.api_target_url": "https://x"})
        run_layer_modes(tmp_path, dry_run=False, quiet=True)
        second = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert second.applied is False
        assert second.changes == []

    def test_dry_run_does_not_modify(self, tmp_path: Path):
        path = _make_forge_toml(
            tmp_path, {"frontend.api_target_url": "https://x.example.com"}
        )
        before = path.read_text(encoding="utf-8")
        report = run_layer_modes(tmp_path, dry_run=True, quiet=True)
        # Report records the change even in dry-run, but file is unchanged.
        assert report.changes
        assert path.read_text(encoding="utf-8") == before

    def test_canonical_already_set_skipped(self, tmp_path: Path):
        """When both the alias and the canonical path are present, the
        rewriter leaves both in place rather than silently dropping the
        alias — the resolver's conflict check surfaces it to the user."""
        _make_forge_toml(
            tmp_path,
            {
                "frontend.api_target_url": "https://legacy",
                "frontend.api_target.url": "https://new",
            },
        )
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert report.applied is False
        body = (tmp_path / "forge.toml").read_text(encoding="utf-8")
        assert "frontend.api_target_url" in body
        assert "frontend.api_target.url" in body

    def test_no_aliases_returns_skipped(self, tmp_path: Path):
        _make_forge_toml(tmp_path, {"frontend.api_target.url": "https://x"})
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert report.applied is False
        assert "No aliased" in (report.skipped_reason or "")


# -- YAML roundtrip ----------------------------------------------------------


class TestYamlRoundtrip:
    def _write_yaml(self, root: Path, name: str = "forge-config.yaml") -> Path:
        path = root / name
        path.write_text(
            "project_name: Demo\n"
            "options:\n"
            "  backend.mode: none\n"
            "  frontend.api_target_url: https://api.example.com\n",
            encoding="utf-8",
        )
        return path

    def test_rewrite_happens(self, tmp_path: Path):
        path = self._write_yaml(tmp_path)
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert report.applied is True
        body = path.read_text(encoding="utf-8")
        assert "frontend.api_target.url" in body
        assert "frontend.api_target_url" not in body
        # Unrelated keys (project_name, backend.mode) untouched.
        assert "Demo" in body
        assert "backend.mode" in body

    def test_second_pass_is_noop(self, tmp_path: Path):
        self._write_yaml(tmp_path)
        run_layer_modes(tmp_path, dry_run=False, quiet=True)
        second = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert second.applied is False

    def test_file_without_options_block_skipped(self, tmp_path: Path):
        path = tmp_path / "not-forge.yaml"
        path.write_text("some_other_key:\n  nested: value\n", encoding="utf-8")
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        # File was silently skipped — no changes recorded for it.
        assert all("not-forge.yaml" not in c for c in report.changes)


# -- JSON roundtrip ----------------------------------------------------------


class TestJsonRoundtrip:
    def test_rewrite_happens(self, tmp_path: Path):
        path = tmp_path / "forge-config.json"
        path.write_text(
            json.dumps(
                {
                    "project_name": "Demo",
                    "options": {
                        "frontend.api_target_url": "https://api.example.com",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert report.applied is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "frontend.api_target.url" in data["options"]
        assert "frontend.api_target_url" not in data["options"]

    def test_second_pass_is_noop(self, tmp_path: Path):
        path = tmp_path / "forge-config.json"
        path.write_text(
            json.dumps({"options": {"frontend.api_target_url": "https://x"}}),
            encoding="utf-8",
        )
        run_layer_modes(tmp_path, dry_run=False, quiet=True)
        second = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert second.applied is False


# -- Degenerate inputs -------------------------------------------------------


class TestDegenerate:
    def test_missing_project_root(self, tmp_path: Path):
        report = run_layer_modes(tmp_path / "does-not-exist", dry_run=False, quiet=True)
        assert report.applied is False
        assert "does not exist" in (report.skipped_reason or "")

    def test_no_config_files(self, tmp_path: Path):
        report = run_layer_modes(tmp_path, dry_run=False, quiet=True)
        assert report.applied is False

"""Tests for the forge.toml read/write module."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from forge.forge_toml import ForgeTomlData, read_forge_toml, write_forge_toml


class TestWriteForgeToml:
    def test_canonical_shape_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="acme",
            templates={"python": "services/python-service-template"},
            features={
                "rate_limit": {"enabled": True, "options": {"requests_per_minute": 120}},
                "rag_pipeline": {"enabled": True, "options": {}},
            },
        )
        data = read_forge_toml(path)
        assert data.version == "0.2.0"
        assert data.project_name == "acme"
        assert data.templates == {"python": "services/python-service-template"}
        assert data.features == {
            "rate_limit": {"enabled": True, "options": {"requests_per_minute": 120}},
            "rag_pipeline": {"enabled": True, "options": {}},
        }
        assert data.legacy_features_format is False

    def test_feature_entries_sorted(self, tmp_path: Path) -> None:
        """Canonical order is alphabetical for diff stability."""
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="x",
            templates={"python": "p"},
            features={
                "zeta": {"enabled": True, "options": {}},
                "alpha": {"enabled": True, "options": {}},
                "mu": {"enabled": True, "options": {}},
            },
        )
        text = path.read_text(encoding="utf-8")
        assert text.index("[forge.features.alpha]") < text.index("[forge.features.mu]")
        assert text.index("[forge.features.mu]") < text.index("[forge.features.zeta]")

    def test_empty_features_emits_empty_section(self, tmp_path: Path) -> None:
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="bare",
            templates={"python": "p"},
            features={},
        )
        data = read_forge_toml(path)
        assert data.features == {}


class TestReadForgeToml:
    def _write(self, tmp_path: Path, content: str) -> Path:
        path = tmp_path / "forge.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            read_forge_toml(tmp_path / "ghost.toml")

    def test_missing_forge_section_raises(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, "[something_else]\nx = 1\n")
        with pytest.raises(ValueError, match=r"\[forge\] section"):
            read_forge_toml(path)

    def test_legacy_flat_list_accepted(self, tmp_path: Path) -> None:
        """Old forge versions wrote [forge.features] enabled = [...]."""
        path = self._write(
            tmp_path,
            "\n".join(
                [
                    "[forge]",
                    'version = "0.1.0"',
                    'project_name = "legacy"',
                    "[forge.templates]",
                    'python = "services/python-service-template"',
                    "[forge.features]",
                    'enabled = ["rate_limit", "security_headers"]',
                    "",
                ]
            ),
        )
        data = read_forge_toml(path)
        assert data.legacy_features_format is True
        assert data.features == {
            "rate_limit": {"enabled": True, "options": {}},
            "security_headers": {"enabled": True, "options": {}},
        }

    def test_disabled_feature_round_trips(self, tmp_path: Path) -> None:
        """A feature explicitly disabled in forge.toml is preserved on read."""
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="x",
            templates={"python": "p"},
            features={"webhooks": {"enabled": False, "options": {}}},
        )
        data = read_forge_toml(path)
        assert data.features["webhooks"]["enabled"] is False

    def test_malformed_feature_entry_skipped(self, tmp_path: Path) -> None:
        """A scalar under [forge.features] is ignored with a warning, not crashed."""
        path = self._write(
            tmp_path,
            "\n".join(
                [
                    "[forge]",
                    'version = "0.2.0"',
                    'project_name = "x"',
                    "[forge.templates]",
                    'python = "p"',
                    "[forge.features]",
                    'broken_scalar = "not a table"',
                    "[forge.features.good]",
                    "enabled = true",
                    "options = {}",
                    "",
                ]
            ),
        )
        data = read_forge_toml(path)
        assert "good" in data.features
        assert "broken_scalar" not in data.features


class TestWriterProducesValidToml:
    def test_output_parses_with_tomlkit(self, tmp_path: Path) -> None:
        """Sanity: the writer emits syntactically valid TOML."""
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="valid",
            templates={"python": "p", "vue": "v"},
            features={"x": {"enabled": True, "options": {"k": "v"}}},
        )
        # Should parse cleanly with tomlkit (used by generator too).
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        assert doc["forge"]["project_name"] == "valid"
        assert doc["forge"]["features"]["x"]["options"]["k"] == "v"


class TestDataclass:
    def test_fields_defaults(self) -> None:
        data = ForgeTomlData(version="0.1", project_name="x")
        assert data.templates == {}
        assert data.features == {}
        assert data.legacy_features_format is False

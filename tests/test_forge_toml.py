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
            options={
                "middleware.rate_limit": True,
                "rag.backend": "qdrant",
                "rag.top_k": 10,
            },
        )
        data = read_forge_toml(path)
        assert data.version == "0.2.0"
        assert data.project_name == "acme"
        assert data.templates == {"python": "services/python-service-template"}
        assert data.options == {
            "middleware.rate_limit": True,
            "rag.backend": "qdrant",
            "rag.top_k": 10,
        }

    def test_option_entries_sorted(self, tmp_path: Path) -> None:
        """Canonical order is alphabetical for diff stability."""
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="x",
            templates={"python": "p"},
            options={
                "rag.top_k": 5,
                "middleware.rate_limit": True,
                "observability.tracing": False,
            },
        )
        text = path.read_text(encoding="utf-8")
        # Dotted keys are preserved in quoted form; order must be alpha.
        rate_limit_pos = text.index('"middleware.rate_limit"')
        tracing_pos = text.index('"observability.tracing"')
        top_k_pos = text.index('"rag.top_k"')
        assert rate_limit_pos < tracing_pos < top_k_pos

    def test_empty_options_emits_empty_section(self, tmp_path: Path) -> None:
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="bare",
            templates={"python": "p"},
            options={},
        )
        data = read_forge_toml(path)
        assert data.options == {}


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

    def test_legacy_features_table_rejected(self, tmp_path: Path) -> None:
        """Old forge.toml with [forge.features] must error — no silent
        auto-migration."""
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
                    'enabled = ["rate_limit"]',
                    "",
                ]
            ),
        )
        with pytest.raises(ValueError, match=r"legacy \[forge\.features\]"):
            read_forge_toml(path)

    def test_legacy_parameters_table_rejected(self, tmp_path: Path) -> None:
        """[forge.parameters] is a pre-Option shape — hard cutover rejects it."""
        path = self._write(
            tmp_path,
            "\n".join(
                [
                    "[forge]",
                    'version = "0.1.0"',
                    'project_name = "legacy"',
                    "[forge.templates]",
                    'python = "p"',
                    "[forge.parameters]",
                    'rag-backend = "qdrant"',
                    "",
                ]
            ),
        )
        with pytest.raises(ValueError, match=r"legacy \[forge\.parameters\]"):
            read_forge_toml(path)

    def test_option_values_unwrap_to_native_types(self, tmp_path: Path) -> None:
        """tomlkit wrapper types are normalized to native Python on read."""
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="x",
            templates={"python": "p"},
            options={"middleware.rate_limit": False, "rag.top_k": 7},
        )
        data = read_forge_toml(path)
        assert type(data.options["middleware.rate_limit"]) is bool
        assert type(data.options["rag.top_k"]) is int
        assert data.options["middleware.rate_limit"] is False
        assert data.options["rag.top_k"] == 7


class TestWriterProducesValidToml:
    def test_output_parses_with_tomlkit(self, tmp_path: Path) -> None:
        """Sanity: the writer emits syntactically valid TOML."""
        path = tmp_path / "forge.toml"
        write_forge_toml(
            path,
            version="0.2.0",
            project_name="valid",
            templates={"python": "p", "vue": "v"},
            options={"rag.backend": "qdrant", "middleware.rate_limit": True},
        )
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
        assert doc["forge"]["project_name"] == "valid"
        assert doc["forge"]["options"]["rag.backend"] == "qdrant"
        assert doc["forge"]["options"]["middleware.rate_limit"] is True


class TestDataclass:
    def test_fields_defaults(self) -> None:
        data = ForgeTomlData(version="0.1", project_name="x")
        assert data.templates == {}
        assert data.options == {}

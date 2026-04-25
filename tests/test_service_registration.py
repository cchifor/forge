"""Tests for the RFC-009 services.yaml parser (P1.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge.service_registration import (
    ServicesYamlError,
    load_services_yaml,
    services_for_language,
)


def _write(path: Path, body: dict) -> None:
    path.write_text(yaml.safe_dump(body), encoding="utf-8")


class TestLoadServicesYaml:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_services_yaml(tmp_path / "missing.yaml") == ()

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        path.write_text("", encoding="utf-8")
        assert load_services_yaml(path) == ()

    def test_valid_minimal_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {
                        "name": "anthropic_client",
                        "type": "AnthropicClient",
                        "import_path": "app.services.anthropic",
                        "scope": "singleton",
                        "languages": ["python"],
                    }
                ]
            },
        )
        services = load_services_yaml(path)
        assert len(services) == 1
        svc = services[0]
        assert svc.name == "anthropic_client"
        assert svc.scope == "singleton"
        assert svc.languages == ("python",)
        assert svc.dependencies == ()
        assert svc.config_key == ""
        assert svc.startup is False

    def test_full_entry(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {
                        "name": "rag_pipeline",
                        "type": "RagPipeline",
                        "import_path": "app.rag.pipeline",
                        "scope": "request",
                        "languages": ["python", "node"],
                        "dependencies": ["vector_store", "embeddings_provider"],
                        "config_key": "rag",
                        "startup": True,
                        "shutdown_hook": "close",
                    }
                ]
            },
        )
        svc = load_services_yaml(path)[0]
        assert svc.scope == "request"
        assert svc.languages == ("python", "node")
        assert svc.dependencies == ("vector_store", "embeddings_provider")
        assert svc.config_key == "rag"
        assert svc.startup is True
        assert svc.shutdown_hook == "close"


class TestParserValidation:
    def test_top_level_not_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(path, {"services": {"not": "a list"}})
        with pytest.raises(ServicesYamlError, match="must be a list"):
            load_services_yaml(path)

    def test_missing_required_key_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {"name": "x", "type": "X", "scope": "singleton", "languages": ["python"]}
                ]
            },
        )
        with pytest.raises(ServicesYamlError, match="import_path"):
            load_services_yaml(path)

    def test_invalid_scope_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {
                        "name": "x",
                        "type": "X",
                        "import_path": "x",
                        "scope": "global",
                        "languages": ["python"],
                    }
                ]
            },
        )
        with pytest.raises(ServicesYamlError, match="scope must be one of"):
            load_services_yaml(path)

    def test_unknown_language_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {
                        "name": "x",
                        "type": "X",
                        "import_path": "x",
                        "scope": "singleton",
                        "languages": ["go"],
                    }
                ]
            },
        )
        with pytest.raises(ServicesYamlError, match="unknown language"):
            load_services_yaml(path)

    def test_dependencies_not_a_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {
                        "name": "x",
                        "type": "X",
                        "import_path": "x",
                        "scope": "singleton",
                        "languages": ["python"],
                        "dependencies": "single_string",
                    }
                ]
            },
        )
        with pytest.raises(ServicesYamlError, match="dependencies must be a list"):
            load_services_yaml(path)


class TestServicesForLanguage:
    def test_filters_to_matching_language(self, tmp_path: Path) -> None:
        path = tmp_path / "services.yaml"
        _write(
            path,
            {
                "services": [
                    {
                        "name": "py_only",
                        "type": "X",
                        "import_path": "x",
                        "scope": "singleton",
                        "languages": ["python"],
                    },
                    {
                        "name": "all_three",
                        "type": "Y",
                        "import_path": "y",
                        "scope": "singleton",
                        "languages": ["python", "node", "rust"],
                    },
                ]
            },
        )
        services = load_services_yaml(path)
        py = services_for_language(services, "python")
        assert {s.name for s in py} == {"py_only", "all_three"}
        node = services_for_language(services, "node")
        assert {s.name for s in node} == {"all_three"}
        rust = services_for_language(services, "rust")
        assert {s.name for s in rust} == {"all_three"}

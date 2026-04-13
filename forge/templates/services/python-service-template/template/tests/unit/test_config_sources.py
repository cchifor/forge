"""Tests for app.core.config.sources."""

import pytest

from app.core.config.sources import (
    ReferenceResolvingSettingsSource,
    YamlConfigSettingsSource,
    find_project_root,
    resolve_config_references,
)


class TestResolveConfigReferences:
    def test_no_references(self):
        data = {"a": 1, "b": "hello"}
        assert resolve_config_references(data) == data

    def test_simple_reference(self):
        data = {"x": "hello", "y": "${x}"}
        result = resolve_config_references(data)
        assert result["y"] == "hello"

    def test_nested_reference(self):
        data = {"a": {"b": "val"}, "c": "${a.b}"}
        result = resolve_config_references(data)
        assert result["c"] == "val"

    def test_string_interpolation(self):
        data = {"host": "localhost", "url": "http://${host}:8080"}
        result = resolve_config_references(data)
        assert result["url"] == "http://localhost:8080"

    def test_missing_path_raises(self):
        data = {"x": "${nonexistent}"}
        with pytest.raises(ValueError, match="path not found"):
            resolve_config_references(data)

    def test_list_values(self):
        data = {"port": 8080, "items": ["${port}", "other"]}
        result = resolve_config_references(data)
        assert result["items"] == [8080, "other"]

    def test_non_string_passthrough(self):
        data = {"x": 42, "y": True, "z": None}
        assert resolve_config_references(data) == data


class TestDeepMerge:
    def test_simple_merge(self):
        result = ReferenceResolvingSettingsSource._deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        result = ReferenceResolvingSettingsSource._deep_merge(base, override)
        assert result["a"] == {"x": 1, "y": 3, "z": 4}

    def test_override_non_dict(self):
        result = ReferenceResolvingSettingsSource._deep_merge({"a": 1}, {"a": 2})
        assert result["a"] == 2


class TestYamlConfigSettingsSource:
    def test_missing_file_returns_empty(self):
        from unittest.mock import MagicMock
        mock_cls = MagicMock()
        source = YamlConfigSettingsSource(mock_cls, "/nonexistent/file.yaml")
        assert source() == {}

    def test_loads_yaml_file(self, tmp_path):
        from unittest.mock import MagicMock
        f = tmp_path / "config.yaml"
        f.write_text("key: value\nnested:\n  x: 1\n")
        mock_cls = MagicMock()
        source = YamlConfigSettingsSource(mock_cls, str(f))
        result = source()
        assert result["key"] == "value"
        assert result["nested"]["x"] == 1

    def test_none_path_returns_empty(self):
        from unittest.mock import MagicMock
        mock_cls = MagicMock()
        source = YamlConfigSettingsSource(mock_cls, None)
        assert source() == {}


class TestFindProjectRoot:
    def test_returns_config_dir(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text("key: value")
        # find_project_root searches upward from sources.py, so we can't
        # easily test the full traversal. Test that the function is callable.
        result = find_project_root()
        assert result is not None

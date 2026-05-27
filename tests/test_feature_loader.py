"""Tests for forge.feature_loader: topo sort, reset, and module-level state."""

from __future__ import annotations

import pytest

from forge import feature_loader, plugins
from forge.errors import FEATURE_DEPENDENCY_CYCLE, FEATURE_DEPENDENCY_MISSING, PluginError
from forge.feature_loader import _topo_sort
from forge.feature_manifest import FeatureManifest
from forge.fragments import FRAGMENT_REGISTRY
from forge.options._registry import OPTION_REGISTRY


def _manifest(name: str, depends: dict[str, str] | None = None) -> FeatureManifest:
    return FeatureManifest(
        name=name,
        version="1.0.0",
        summary="test",
        category="test",
        depends=depends or {},
        provides_options=(),
        provides_fragments=(),
        module_path=f"forge.features.{name}",
        manifest_path=f"/fake/{name}/feature.toml",
    )


@pytest.fixture(autouse=True)
def _reset():
    feature_loader.reset_for_tests()
    plugins.reset_for_tests()
    yield
    feature_loader.reset_for_tests()
    plugins.reset_for_tests()


class TestTopoSort:
    def test_no_deps_preserves_alphabetical_order(self) -> None:
        manifests = [_manifest("delta"), _manifest("alpha"), _manifest("charlie")]
        result = _topo_sort(manifests)
        names = [m.name for m in result]
        assert names == ["alpha", "charlie", "delta"]

    def test_deps_ordered_correctly(self) -> None:
        a = _manifest("a", depends={"b": ">=1.0"})
        b = _manifest("b")
        result = _topo_sort([a, b])
        names = [m.name for m in result]
        assert names.index("b") < names.index("a")

    def test_diamond_dependency(self) -> None:
        a = _manifest("a", depends={"b": "*", "c": "*"})
        b = _manifest("b", depends={"d": "*"})
        c = _manifest("c", depends={"d": "*"})
        d = _manifest("d")
        result = _topo_sort([a, b, c, d])
        names = [m.name for m in result]
        assert names.index("d") < names.index("b")
        assert names.index("d") < names.index("c")
        assert names.index("b") < names.index("a")
        assert names.index("c") < names.index("a")

    def test_missing_dep_raises(self) -> None:
        a = _manifest("a", depends={"nonexistent": "*"})
        with pytest.raises(PluginError, match="nonexistent") as exc_info:
            _topo_sort([a])
        assert exc_info.value.code == FEATURE_DEPENDENCY_MISSING

    def test_cycle_raises(self) -> None:
        a = _manifest("a", depends={"b": "*"})
        b = _manifest("b", depends={"a": "*"})
        with pytest.raises(PluginError, match="cycle") as exc_info:
            _topo_sort([a, b])
        assert exc_info.value.code == FEATURE_DEPENDENCY_CYCLE

    def test_self_cycle_raises(self) -> None:
        a = _manifest("a", depends={"a": "*"})
        with pytest.raises(PluginError, match="cycle") as exc_info:
            _topo_sort([a])
        assert exc_info.value.code == FEATURE_DEPENDENCY_CYCLE


class TestResetForTests:
    def test_reset_clears_loaded_features(self) -> None:
        feature_loader.LOADED_FEATURES.append(_manifest("x"))
        feature_loader.LOADED_FEATURES.append(_manifest("y"))
        assert len(feature_loader.LOADED_FEATURES) == 2

        feature_loader.reset_for_tests()

        assert feature_loader.LOADED_FEATURES == []

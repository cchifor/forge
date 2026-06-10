"""Integration tests for the unified feature/plugin architecture.

Verifies that real features load correctly through the manifest-driven
discovery pipeline: TOML parsing, topological sort, ``register()``
dispatch, and post-load contract validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge import feature_loader, plugins
from forge.feature_manifest import (
    FeatureManifest,
    parse_feature_manifest,
    validate_manifest_contracts,
)
from forge.fragments import FRAGMENT_REGISTRY
from forge.options._registry import OPTION_ALIAS_INDEX, OPTION_REGISTRY


# ------------------------------------------------------------------
# Fixture: isolate feature + plugin state between tests
# ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    """Save, reset, and restore all mutable global registries."""
    # Save state
    saved_opts = dict(OPTION_REGISTRY)
    saved_aliases = dict(OPTION_ALIAS_INDEX)
    saved_frags = dict(FRAGMENT_REGISTRY)
    saved_frags_frozen = FRAGMENT_REGISTRY.frozen
    saved_loaded = list(feature_loader.LOADED_FEATURES)

    feature_loader.reset_for_tests()
    plugins.reset_for_tests()
    OPTION_REGISTRY.clear()
    OPTION_ALIAS_INDEX.clear()
    FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.clear()

    yield

    feature_loader.reset_for_tests()
    plugins.reset_for_tests()
    # Restore registries
    OPTION_REGISTRY.clear()
    OPTION_REGISTRY.update(saved_opts)
    OPTION_ALIAS_INDEX.clear()
    OPTION_ALIAS_INDEX.update(saved_aliases)
    FRAGMENT_REGISTRY.frozen = False
    FRAGMENT_REGISTRY.clear()
    FRAGMENT_REGISTRY.update(saved_frags)
    FRAGMENT_REGISTRY.frozen = saved_frags_frozen
    # Restore LOADED_FEATURES in sync with the registries we just restored,
    # so a later load_all() sees a consistent state and correctly no-ops.
    feature_loader.LOADED_FEATURES.clear()
    feature_loader.LOADED_FEATURES.extend(saved_loaded)
    # Keep the per-phase guard in sync with the restored roster.
    feature_loader._BUILTINS_LOADED = bool(saved_loaded)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_FEATURES_DIR = Path(__file__).resolve().parent.parent / "forge" / "features"


def _discover_manifests() -> list[FeatureManifest]:
    """Scan the real features directory and return parsed manifests."""
    manifests = []
    for toml_path in sorted(_FEATURES_DIR.glob("*/feature.toml")):
        dir_name = toml_path.parent.name
        manifest = parse_feature_manifest(
            toml_path,
            module_path=f"forge.features.{dir_name}",
        )
        manifests.append(manifest)
    return manifests


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestManifestDiscovery:
    def test_all_manifests_discovered(self) -> None:
        """Every feature directory has a parseable feature.toml."""
        manifests = _discover_manifests()
        assert len(manifests) == 33, (
            f"Expected 33 feature manifests, discovered {len(manifests)}: "
            f"{sorted(m.name for m in manifests)}"
        )

    def test_topo_sort_orders_deps_correctly(self) -> None:
        """Topological sort honours declared dependencies."""
        manifests = _discover_manifests()
        ordered = feature_loader._topo_sort(manifests)
        names = [m.name for m in ordered]

        # rag depends on conversation and async_work
        assert names.index("conversation") < names.index("rag")
        assert names.index("async_work") < names.index("rag")

        # streaming depends on events
        assert names.index("events") < names.index("streaming")

        # agent depends on conversation
        assert names.index("conversation") < names.index("agent")


class TestLoadAll:
    def test_load_all_populates_loaded_features(self) -> None:
        """load_all() discovers and loads all 28 built-in features."""
        result = feature_loader.load_all()
        assert len(result) == 33
        assert len(feature_loader.LOADED_FEATURES) == 33

        loaded_names = {m.name for m in feature_loader.LOADED_FEATURES}
        # Spot-check a few features from different categories
        assert "rag" in loaded_names
        assert "auth" in loaded_names
        assert "streaming" in loaded_names
        assert "conversation" in loaded_names

    def test_load_all_registers_all_options(self) -> None:
        """After load_all(), every option declared in manifests is registered."""
        feature_loader.load_all()

        # Collect all option paths declared across all manifests
        declared_options: set[str] = set()
        for manifest in feature_loader.LOADED_FEATURES:
            declared_options.update(manifest.provides_options)

        registered_options = set(OPTION_REGISTRY.keys())
        missing = declared_options - registered_options
        assert not missing, (
            f"Options declared in manifests but not registered: {sorted(missing)}"
        )

    def test_load_all_registers_all_fragments(self) -> None:
        """After load_all(), every fragment declared in manifests is registered."""
        feature_loader.load_all()

        # Collect all fragment names declared across all manifests
        declared_fragments: set[str] = set()
        for manifest in feature_loader.LOADED_FEATURES:
            declared_fragments.update(manifest.provides_fragments)

        registered_fragments = set(FRAGMENT_REGISTRY.keys())
        missing = declared_fragments - registered_fragments
        assert not missing, (
            f"Fragments declared in manifests but not registered: {sorted(missing)}"
        )

    def test_load_all_is_idempotent(self) -> None:
        """Calling load_all() twice returns the same list object."""
        first = feature_loader.load_all()
        second = feature_loader.load_all()
        assert first is second
        assert len(first) == 33

    def test_load_all_tolerates_loaded_features_desync(self) -> None:
        """load_all() must not re-register when registries are already
        populated but LOADED_FEATURES was cleared out of sync.

        Reproduces the class of bug where in-process state drifts (e.g. a
        test fixture clears LOADED_FEATURES but leaves OPTION_REGISTRY
        populated). A naive re-register would raise PLUGIN_COLLISION on the
        already-present options; the registry-level idempotency guard must
        skip those features instead.
        """
        feature_loader.load_all()
        assert len(feature_loader.LOADED_FEATURES) == 33
        n_options = len(OPTION_REGISTRY)
        n_fragments = len(FRAGMENT_REGISTRY)

        # Simulate the desync: registries stay populated, but the loader's
        # in-process state is reset (roster emptied + _BUILTINS_LOADED
        # cleared) — exactly what reset_for_tests() does when a fixture has
        # restored the registries out of band.
        feature_loader.LOADED_FEATURES.clear()
        feature_loader._BUILTINS_LOADED = False

        # Must not raise PluginError("already registered"), and must rebuild
        # the roster to a consistent state without duplicating registrations.
        result = feature_loader.load_all()
        assert len(result) == 33
        assert len(OPTION_REGISTRY) == n_options
        assert len(FRAGMENT_REGISTRY) == n_fragments


class TestContractValidation:
    def test_manifest_contracts_valid(self) -> None:
        """After load_all(), validate_manifest_contracts returns no violations."""
        feature_loader.load_all()

        registered_options = frozenset(OPTION_REGISTRY.keys())
        registered_fragments = frozenset(FRAGMENT_REGISTRY.keys())

        all_violations: dict[str, list[str]] = {}
        for manifest in feature_loader.LOADED_FEATURES:
            violations = validate_manifest_contracts(
                manifest, registered_options, registered_fragments,
            )
            if violations:
                all_violations[manifest.name] = violations

        assert not all_violations, (
            f"Contract violations found: {all_violations}"
        )


class TestLoadOrder:
    def test_load_all_respects_dependency_order(self) -> None:
        """Features are loaded in order: deps before dependents."""
        feature_loader.load_all()
        names = [m.name for m in feature_loader.LOADED_FEATURES]
        assert names.index("conversation") < names.index("rag")
        assert names.index("async_work") < names.index("rag")
        assert names.index("events") < names.index("streaming")
        assert names.index("conversation") < names.index("agent")


class TestCrossFeatureDeps:
    def test_cross_feature_fragment_deps_resolve(self) -> None:
        """rag_pipeline's depends_on(conversation_persistence) resolves.

        The rag feature declares depends_on=("conversation_persistence",)
        on rag_pipeline. After load_all(), the conversation feature must
        have registered conversation_persistence in FRAGMENT_REGISTRY so
        rag_pipeline's dependency is satisfiable.
        """
        feature_loader.load_all()
        assert "conversation_persistence" in FRAGMENT_REGISTRY
        assert "rag_pipeline" in FRAGMENT_REGISTRY

        rag_pipeline = FRAGMENT_REGISTRY["rag_pipeline"]
        assert "conversation_persistence" in rag_pipeline.depends_on

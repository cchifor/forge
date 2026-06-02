"""Tests for the component update-plan engine (Phase 2).

``component_update_diff`` powers ``forge --plan-update`` for layered artifacts:
given the set of components whose definition changed, it computes the
regenerate/skip set — regenerate = the changed components ∪ their transitive
*dependents* (never their dependencies) — annotated with reasons.
``component_fingerprint`` is the per-component SHA that change-detection compares
against the provenance baseline.
"""

from __future__ import annotations

from forge.components import (
    ComponentNode,
    build_registry_from_manifests,
    component_fingerprint,
    component_update_diff,
    populate_from_manifests,
    resolve_components,
)
from forge.components._registry import COMPONENT_REGISTRY
from forge.feature_manifest import FeatureManifest


def _node(name: str, layer: int, **kw) -> ComponentNode:
    return ComponentNode(name=name, layer=layer, **kw)


def _chain() -> dict[str, ComponentNode]:
    # A (L1) <- Panel (L2) <- Page (L3)
    return {
        "A": _node("A", 1),
        "Panel": _node("Panel", 2, children={"A": "*"}),
        "Page": _node("Page", 3, children={"Panel": "*"}),
    }


class TestComponentUpdateDiff:
    def test_changed_leaf_regenerates_all_dependents(self) -> None:
        resolved = resolve_components(["Page"], _chain())
        actions = {a.name: a for a in component_update_diff({"A"}, resolved)}
        assert actions["A"].action == "regenerate"
        assert actions["Panel"].action == "regenerate"
        assert actions["Page"].action == "regenerate"
        assert "changed" in actions["A"].reason
        assert "depend" in actions["Panel"].reason.lower()

    def test_changed_middle_skips_its_dependency(self) -> None:
        resolved = resolve_components(["Page"], _chain())
        actions = {a.name: a for a in component_update_diff({"Panel"}, resolved)}
        # Panel changed → Panel + Page regenerate; A (a dependency) is skipped.
        assert actions["Panel"].action == "regenerate"
        assert actions["Page"].action == "regenerate"
        assert actions["A"].action == "skip"

    def test_no_change_skips_everything(self) -> None:
        resolved = resolve_components(["Page"], _chain())
        actions = component_update_diff(set(), resolved)
        assert {a.action for a in actions} == {"skip"}

    def test_diff_follows_topological_order(self) -> None:
        resolved = resolve_components(["Page"], _chain())
        names = [a.name for a in component_update_diff({"A"}, resolved)]
        assert names == list(resolved.ordered)


class TestRegenerateSet:
    def test_regenerate_set_is_changed_plus_dependents(self) -> None:
        from forge.components import regenerate_set

        resolved = resolve_components(["Page"], _chain())
        assert regenerate_set({"A"}, resolved) == frozenset({"A", "Panel", "Page"})
        assert regenerate_set({"Panel"}, resolved) == frozenset({"Panel", "Page"})
        assert regenerate_set(set(), resolved) == frozenset()


class TestChangedComponents:
    def test_absent_baseline_is_changed(self) -> None:
        from forge.components import changed_components, component_fingerprint

        a = _node("A", 1, version="1.0.0")
        b = _node("B", 1, version="1.0.0")
        # A has a matching baseline; B is absent ⇒ B counts as changed.
        baselines = {"A": component_fingerprint(a)}
        assert changed_components([a, b], baselines) == frozenset({"B"})

    def test_drift_detected(self) -> None:
        from forge.components import changed_components, component_fingerprint

        a = _node("A", 1, version="1.0.0")
        baselines = {"A": component_fingerprint(a)}
        a2 = _node("A", 1, version="2.0.0")  # version changed
        assert changed_components([a2], baselines) == frozenset({"A"})


class TestComponentFingerprint:
    def test_aggregate_order_independent(self) -> None:
        a = _node("P", 2, aggregates=("C1", "C2"))
        b = _node("P", 2, aggregates=("C2", "C1"))
        assert component_fingerprint(a) == component_fingerprint(b)

    def test_stable_for_equal_nodes(self) -> None:
        a = _node("Panel", 2, version="1.0.0", children={"A": "*", "B": "^1.0"})
        b = _node("Panel", 2, version="1.0.0", children={"B": "^1.0", "A": "*"})
        # Child order in the table must not change the fingerprint.
        assert component_fingerprint(a) == component_fingerprint(b)

    def test_changes_with_version(self) -> None:
        a = _node("Panel", 2, version="1.0.0")
        b = _node("Panel", 2, version="1.0.1")
        assert component_fingerprint(a) != component_fingerprint(b)

    def test_changes_with_contract(self) -> None:
        a = _node("List", 1, contract="C1")
        b = _node("List", 1, contract="C2")
        assert component_fingerprint(a) != component_fingerprint(b)


class TestRegistryPopulation:
    def test_populate_from_manifests_fills_only_components(self) -> None:
        comp = FeatureManifest(
            name="Panel",
            version="2.0.0",
            summary="s",
            category="component",
            depends={},
            provides_options=(),
            provides_fragments=(),
            module_path="m",
            manifest_path="p",
            component_layer=2,
        )
        plain = FeatureManifest(
            name="auth",
            version="1.0.0",
            summary="s",
            category="security",
            depends={},
            provides_options=(),
            provides_fragments=(),
            module_path="m",
            manifest_path="p",
        )
        try:
            populate_from_manifests([comp, plain])
            assert set(COMPONENT_REGISTRY) == {"Panel"}
            # Idempotent: a second populate replaces, not accumulates.
            populate_from_manifests([comp])
            assert set(COMPONENT_REGISTRY) == {"Panel"}
        finally:
            COMPONENT_REGISTRY.clear()

    def test_feature_loader_populates_registry_consistently(self) -> None:
        # After the real loader runs, the component registry must equal the
        # component projection of the loaded manifests (empty until Phase 3
        # ships component features, but the wiring must be consistent).
        from forge import feature_loader

        feature_loader.reset_for_tests()
        COMPONENT_REGISTRY.clear()
        manifests = feature_loader.load_builtin_features()
        assert build_registry_from_manifests(manifests) == COMPONENT_REGISTRY

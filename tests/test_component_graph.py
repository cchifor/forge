"""Tests for the layered-component dependency graph (Phase 1).

The component tier sits ABOVE the option/fragment graph: components depend on
same-or-lower-layer components (+ a data contract). ``resolve_components`` walks
the selected closure, enforces the layering rules, satisfies version specs,
topo-sorts (reusing the OPTIONS_DEP_CYCLE error path), and builds a transitive
reverse-dependents index for "regenerate the changed artifact + its dependents".
"""

from __future__ import annotations

import pytest

from forge.components import (
    ComponentNode,
    ResolvedComponents,
    build_registry_from_manifests,
    resolve_components,
)
from forge.errors import (
    FEATURE_DEPENDENCY_MISSING,
    OPTIONS_DEP_CYCLE,
    OptionsError,
    PluginError,
)
from forge.feature_manifest import FeatureManifest


def _node(
    name: str,
    layer: int,
    *,
    version: str = "1.0.0",
    children: dict[str, str] | None = None,
    contract: str | None = None,
    aggregates: tuple[str, ...] = (),
) -> ComponentNode:
    return ComponentNode(
        name=name,
        layer=layer,
        version=version,
        children=children or {},
        contract=contract,
        aggregates=aggregates,
    )


def _reg(*nodes: ComponentNode) -> dict[str, ComponentNode]:
    return {n.name: n for n in nodes}


class TestTopoOrderAndClosure:
    def test_deps_ordered_before_dependents(self) -> None:
        reg = _reg(
            _node("Btn", 1, contract=None),
            _node("Row", 1),
            _node("Panel", 2, children={"Btn": "*", "Row": "*"}),
        )
        res = resolve_components(["Panel"], reg)
        assert isinstance(res, ResolvedComponents)
        assert set(res.ordered) == {"Btn", "Row", "Panel"}
        assert res.ordered.index("Btn") < res.ordered.index("Panel")
        assert res.ordered.index("Row") < res.ordered.index("Panel")

    def test_only_selected_closure_included(self) -> None:
        reg = _reg(
            _node("A", 1),
            _node("Panel", 2, children={"A": "*"}),
            _node("Unrelated", 1),
        )
        res = resolve_components(["Panel"], reg)
        assert "Unrelated" not in res.ordered
        assert set(res.ordered) == {"A", "Panel"}


class TestReverseDependents:
    def test_transitive_dependents_closure(self) -> None:
        reg = _reg(
            _node("A", 1),
            _node("Panel", 2, children={"A": "*"}),
            _node("Page", 3, children={"Panel": "*"}),
        )
        res = resolve_components(["Page"], reg)
        # A changing must regenerate Panel AND Page (transitive).
        assert res.dependents["A"] == frozenset({"Panel", "Page"})
        assert res.dependents["Panel"] == frozenset({"Page"})
        assert res.dependents["Page"] == frozenset()


class TestLayeringRules:
    def test_rejects_upward_dependency(self) -> None:
        # L2 depending on an L3 child is an illegal upward edge.
        reg = _reg(_node("Hi", 3), _node("Low", 2, children={"Hi": "*"}))
        with pytest.raises(PluginError, match="layer"):
            resolve_components(["Low"], reg)

    def test_rejects_layer1_with_children(self) -> None:
        reg = _reg(_node("Leaf", 1), _node("Atom", 1, children={"Leaf": "*"}))
        with pytest.raises(PluginError, match="[Ll]ayer.?1|layer-1|basic"):
            resolve_components(["Atom"], reg)

    def test_allows_same_layer_2_to_2(self) -> None:
        reg = _reg(_node("A", 2), _node("B", 2, children={"A": "*"}))
        res = resolve_components(["B"], reg)
        assert set(res.ordered) == {"A", "B"}

    def test_rejects_same_layer_3_to_3(self) -> None:
        reg = _reg(_node("A", 3), _node("B", 3, children={"A": "*"}))
        with pytest.raises(PluginError, match="[Ll]ayer.?3|template"):
            resolve_components(["B"], reg)

    @pytest.mark.parametrize(
        ("parent_layer", "child_layer"),
        [(2, 1), (3, 1), (3, 2)],
    )
    def test_allows_downward_edges(self, parent_layer: int, child_layer: int) -> None:
        reg = _reg(
            _node("Child", child_layer),
            _node("Parent", parent_layer, children={"Child": "*"}),
        )
        assert set(resolve_components(["Parent"], reg).ordered) == {"Child", "Parent"}


class TestCycleDetection:
    def test_cycle_raises_options_dep_cycle(self) -> None:
        reg = _reg(
            _node("A", 2, children={"B": "*"}),
            _node("B", 2, children={"A": "*"}),
        )
        with pytest.raises(OptionsError) as exc:
            resolve_components(["A"], reg)
        assert exc.value.code == OPTIONS_DEP_CYCLE
        # The cycle members + a concrete closing path are surfaced for the diff.
        assert set(exc.value.context.get("components", [])) >= {"A", "B"}
        path = exc.value.context.get("cycle_path", [])
        assert path and path[0] == path[-1]

    def test_self_loop_is_a_cycle(self) -> None:
        reg = _reg(_node("A", 2, children={"A": "*"}))
        with pytest.raises(OptionsError) as exc:
            resolve_components(["A"], reg)
        assert exc.value.code == OPTIONS_DEP_CYCLE
        assert exc.value.context.get("cycle_path") == ["A", "A"]


class TestVersionSatisfaction:
    def test_missing_child_raises_dependency_missing(self) -> None:
        reg = _reg(_node("Panel", 2, children={"Ghost": "*"}))
        with pytest.raises(PluginError) as exc:
            resolve_components(["Panel"], reg)
        assert exc.value.code == FEATURE_DEPENDENCY_MISSING

    def test_unsatisfiable_version_raises(self) -> None:
        reg = _reg(
            _node("A", 1, version="1.0.0"),
            _node("Panel", 2, children={"A": ">=2.0.0"}),
        )
        with pytest.raises(PluginError) as exc:
            resolve_components(["Panel"], reg)
        assert exc.value.code == FEATURE_DEPENDENCY_MISSING
        assert "A" in str(exc.value)

    def test_satisfiable_version_ok(self) -> None:
        reg = _reg(
            _node("A", 1, version="1.4.0"),
            _node("Panel", 2, children={"A": ">=1.0.0"}),
        )
        res = resolve_components(["Panel"], reg)
        assert set(res.ordered) == {"A", "Panel"}

    def test_star_spec_matches_any(self) -> None:
        reg = _reg(_node("A", 1, version="9.9.9"), _node("P", 2, children={"A": "*"}))
        assert set(resolve_components(["P"], reg).ordered) == {"A", "P"}

    @pytest.mark.parametrize(
        ("spec", "version", "ok"),
        [
            ("^1.0", "1.4.0", True),
            ("^1.0", "2.0.0", False),
            ("^1.2.3", "1.2.3", True),
            ("^1.2.3", "1.9.0", True),
            ("^1.2.3", "2.0.0", False),
            ("^0.2.0", "0.2.5", True),
            ("^0.2.0", "0.3.0", False),
            ("^0.0.3", "0.0.3", True),
            ("^0.0.3", "0.0.4", False),
        ],
    )
    def test_caret_spec(self, spec: str, version: str, ok: bool) -> None:
        # The plan's manifest examples use caret ranges; the resolver must
        # honor them (npm/cargo semantics), not reject as "unparseable".
        reg = _reg(_node("A", 1, version=version), _node("P", 2, children={"A": spec}))
        if ok:
            assert set(resolve_components(["P"], reg).ordered) == {"A", "P"}
        else:
            with pytest.raises(PluginError) as exc:
                resolve_components(["P"], reg)
            assert exc.value.code == FEATURE_DEPENDENCY_MISSING


class TestContracts:
    def test_resolved_contracts_union(self) -> None:
        reg = _reg(
            _node("List", 1, contract="EntityContract"),
            _node("Panel", 2, children={"List": "*"}, aggregates=("ReportContract",)),
        )
        res = resolve_components(["Panel"], reg)
        assert res.contracts == frozenset({"EntityContract", "ReportContract"})

    def test_pure_ui_component_has_no_contract(self) -> None:
        reg = _reg(_node("Spacer", 1))
        res = resolve_components(["Spacer"], reg)
        assert res.contracts == frozenset()


class TestBuildRegistryFromManifests:
    def test_only_component_manifests_become_nodes(self) -> None:
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
            component_children={"List": "^1.0"},
            component_contract="EntityContract",
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
        reg = build_registry_from_manifests([comp, plain])
        assert set(reg) == {"Panel"}  # the plain feature is not a component
        assert reg["Panel"].layer == 2
        assert reg["Panel"].children == {"List": "^1.0"}
        assert reg["Panel"].contract == "EntityContract"

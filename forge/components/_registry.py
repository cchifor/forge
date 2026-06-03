"""The component registry — a parallel to OPTION_REGISTRY / FRAGMENT_REGISTRY.

Components are *also* features (one ``feature.toml`` with ``layer`` set), so the
canonical population path is :func:`build_registry_from_manifests` over the
loaded feature manifests. The module-level :data:`COMPONENT_REGISTRY` mirrors the
other registries for the loader/plugin path; the resolver itself takes an
explicit registry argument so it stays unit-testable in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable

from forge.components._spec import ComponentNode
from forge.errors import PLUGIN_COLLISION, PluginError
from forge.feature_manifest import FeatureManifest

# Module-level registry, mirroring OPTION_REGISTRY / FRAGMENT_REGISTRY. Populated
# by the feature loader / ForgeAPI.add_component (Phase 2). The resolver accepts
# any registry mapping, so tests need not touch this global.
COMPONENT_REGISTRY: dict[str, ComponentNode] = {}


def register_component(node: ComponentNode) -> None:
    """Register a component node, rejecting duplicate names."""
    if node.name in COMPONENT_REGISTRY:
        raise PluginError(
            f"Component {node.name!r} is already registered",
            code=PLUGIN_COLLISION,
            context={"component": node.name},
        )
    COMPONENT_REGISTRY[node.name] = node


def reset_for_tests() -> None:
    """Clear the registry — test-only."""
    COMPONENT_REGISTRY.clear()


def component_node_from_manifest(manifest: FeatureManifest) -> ComponentNode:
    """Project a component ``FeatureManifest`` onto a :class:`ComponentNode`.

    Assumes ``manifest.component_layer`` is set (the caller filters).
    """
    assert manifest.component_layer is not None
    return ComponentNode(
        name=manifest.name,
        layer=manifest.component_layer,
        version=manifest.version,
        children=dict(manifest.component_children),
        contract=manifest.component_contract,
        aggregates=tuple(manifest.component_aggregates),
    )


def build_registry_from_manifests(
    manifests: Iterable[FeatureManifest],
) -> dict[str, ComponentNode]:
    """Build a component registry from manifests, keeping only components.

    A manifest is a component iff ``component_layer`` is set; plain features are
    skipped (they live in the fragment graph, not the component graph).
    """
    return {
        m.name: component_node_from_manifest(m) for m in manifests if m.component_layer is not None
    }


def populate_from_manifests(manifests: Iterable[FeatureManifest]) -> None:
    """Replace :data:`COMPONENT_REGISTRY` with the components in ``manifests``.

    Idempotent: clears first, so the loader can call it after each feature load
    without accumulating stale entries. Plain (non-component) features are
    skipped.
    """
    COMPONENT_REGISTRY.clear()
    COMPONENT_REGISTRY.update(build_registry_from_manifests(manifests))

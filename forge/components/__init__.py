"""Layered-component model — the component tier of the dependency graph.

A *component* is a Layer-1 basic component, a Layer-2 composed component, or a
Layer-3 template. Components depend on same-or-lower-layer components plus a data
contract; this package resolves a component selection into an ordered plan and a
transitive reverse-dependents index, reusing the existing ``OPTIONS_DEP_CYCLE``
error path for cycles. Components compile down into the existing option/fragment
graph for emission (Phase 2) — this tier owns selection, ordering, layering, and
the dependents closure only.
"""

from __future__ import annotations

from forge.components._compile import (
    COMPONENT_TEMPLATES_ROOT,
    component_fragment_name,
    component_fragments,
    register_component_fragments,
)
from forge.components._plan import (
    ComponentAction,
    changed_components,
    component_fingerprint,
    component_update_diff,
    regenerate_set,
)
from forge.components._registry import (
    COMPONENT_REGISTRY,
    build_registry_from_manifests,
    component_node_from_manifest,
    populate_from_manifests,
    register_component,
    reset_for_tests,
)
from forge.components._resolver import ResolvedComponents, resolve_components
from forge.components._spec import ComponentNode

__all__ = [
    "COMPONENT_REGISTRY",
    "COMPONENT_TEMPLATES_ROOT",
    "ComponentAction",
    "component_fragment_name",
    "component_fragments",
    "ComponentNode",
    "ResolvedComponents",
    "build_registry_from_manifests",
    "changed_components",
    "component_fingerprint",
    "component_node_from_manifest",
    "component_update_diff",
    "populate_from_manifests",
    "regenerate_set",
    "register_component",
    "register_component_fragments",
    "reset_for_tests",
    "resolve_components",
]

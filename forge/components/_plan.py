"""Component update-plan + change-detection helpers (Phase 2).

These are templates-independent: they operate on the resolved component graph,
not on emitted files. ``component_update_diff`` is the dependency-graph diff that
``forge --plan-update`` renders for layered artifacts; ``component_fingerprint``
is the per-component SHA recorded in provenance so a subsequent run can tell
which component *definitions* changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Set
from dataclasses import dataclass

from forge.components._resolver import ResolvedComponents
from forge.components._spec import ComponentNode


@dataclass(frozen=True)
class ComponentAction:
    """One row of the component update plan."""

    name: str
    action: str  # "regenerate" | "skip"
    reason: str


def component_update_diff(
    changed: Set[str], resolved: ResolvedComponents
) -> tuple[ComponentAction, ...]:
    """Compute the regenerate/skip plan for a set of changed components.

    Regenerate = the changed components ∪ their transitive *dependents*
    (artifacts that depend on a changed one), never their dependencies. The
    result follows ``resolved.ordered`` so the plan reads dependencies-first.
    """
    regenerate: set[str] = set(changed)
    for name in changed:
        regenerate |= resolved.dependents.get(name, frozenset())

    actions: list[ComponentAction] = []
    for name in resolved.ordered:
        if name in changed:
            actions.append(ComponentAction(name, "regenerate", "changed"))
        elif name in regenerate:
            actions.append(ComponentAction(name, "regenerate", "depends on a changed component"))
        else:
            actions.append(ComponentAction(name, "skip", "unchanged"))
    return tuple(actions)


def regenerate_set(changed: Set[str], resolved: ResolvedComponents) -> frozenset[str]:
    """The set of components to regenerate = changed ∪ transitive dependents."""
    out: set[str] = set(changed)
    for name in changed:
        out |= resolved.dependents.get(name, frozenset())
    return frozenset(out)


def component_fingerprint(node: ComponentNode) -> str:
    """Deterministic SHA-256 of a component's definition.

    Order-independent over ``children`` / ``aggregates`` so a cosmetic reorder
    in ``feature.toml`` does not look like a change. Used as the provenance
    baseline for component change-detection.
    """
    payload = json.dumps(
        {
            "name": node.name,
            "layer": node.layer,
            "version": node.version,
            "children": dict(sorted(node.children.items())),
            "contract": node.contract,
            "aggregates": sorted(node.aggregates),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def changed_components(nodes: Iterable[ComponentNode], baselines: dict[str, str]) -> frozenset[str]:
    """Names whose current fingerprint differs from the recorded baseline.

    A component absent from ``baselines`` is treated as changed (newly added).
    """
    out: set[str] = set()
    for node in nodes:
        if component_fingerprint(node) != baselines.get(node.name):
            out.add(node.name)
    return frozenset(out)

"""Resolve a component selection into an ordered plan + dependents index.

This is the component *tier* of the dependency graph — it sits above the
existing option/fragment resolver. Given a selection of component names and a
registry, :func:`resolve_components`:

1. walks the transitive child closure, validating each edge for presence,
   version satisfaction, and the layering rule;
2. topologically sorts the closure (children before parents), reusing the
   existing ``OPTIONS_DEP_CYCLE`` error path with an explicit cycle-path in the
   error ``context``;
3. builds a **transitive reverse-dependents index** so a changed artifact can
   regenerate exactly its dependents (not its dependencies);
4. unions the data contracts the selected components consume/aggregate.

Layering rule (enforced here): a dependency may only point at the same or a
lower layer. Upward edges (1→2, 2→3) are illegal. Same-layer 2→2 is allowed;
3→3 is disallowed; a Layer-1 component may not declare child components at all
(it composes only a data contract).
"""

from __future__ import annotations

from dataclasses import dataclass

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from forge.components._spec import ComponentNode
from forge.errors import (
    FEATURE_CONTRACT_VIOLATION,
    FEATURE_DEPENDENCY_MISSING,
    OPTIONS_DEP_CYCLE,
    OptionsError,
    PluginError,
)

_ANY_SPECS = frozenset({"", "*"})


def _caret_to_range(version: str) -> str:
    """Translate an npm/cargo caret version into a PEP 440 range.

    ``^1.2.3`` → ``>=1.2.3,<2.0.0``; ``^0.2.0`` → ``>=0.2.0,<0.3.0``;
    ``^0.0.3`` → ``>=0.0.3,<0.0.4``. 1- and 2-component forms pad with zeros
    (``^1.0`` → ``>=1.0.0,<2.0.0``). Raises ``ValueError`` on a non-numeric
    component (the caller maps that to an unparseable-spec error).
    """
    nums = [int(p) for p in version.split(".")]
    while len(nums) < 3:
        nums.append(0)
    major, minor, patch = nums[0], nums[1], nums[2]
    if major > 0:
        upper = f"{major + 1}.0.0"
    elif minor > 0:
        upper = f"0.{minor + 1}.0"
    else:
        upper = f"0.0.{patch + 1}"
    return f">={major}.{minor}.{patch},<{upper}"


def _to_specifier_set(spec: str) -> SpecifierSet:
    """Build a SpecifierSet, supporting the caret (``^``) range shorthand."""
    s = spec.strip()
    if s.startswith("^"):
        return SpecifierSet(_caret_to_range(s[1:]))
    return SpecifierSet(s)


@dataclass(frozen=True)
class ResolvedComponents:
    """Output of :func:`resolve_components`.

    ``ordered`` lists every component in the selected closure with children
    before parents. ``dependents`` maps each component to the transitive set of
    components that (directly or indirectly) depend on it. ``contracts`` is the
    union of every contract consumed or aggregated across the closure.
    """

    ordered: tuple[str, ...]
    dependents: dict[str, frozenset[str]]
    contracts: frozenset[str]


def _version_satisfies(parent: str, child: str, child_version: str, spec: str) -> None:
    """Raise ``FEATURE_DEPENDENCY_MISSING`` if ``child_version`` fails ``spec``.

    ``spec`` is a PEP 440 specifier; ``""`` / ``"*"`` mean "any version".
    """
    if spec.strip() in _ANY_SPECS:
        return
    try:
        satisfied = Version(child_version) in _to_specifier_set(spec)
    except ValueError as exc:  # InvalidSpecifier/InvalidVersion subclass ValueError
        raise PluginError(
            f"Component {parent!r} declares an unparseable version spec "
            f"{spec!r} for child {child!r}: {exc}",
            code=FEATURE_DEPENDENCY_MISSING,
            context={"component": parent, "child": child, "spec": spec},
        ) from exc
    if not satisfied:
        raise PluginError(
            f"Component {parent!r} requires {child} {spec}, but {child} is "
            f"version {child_version} — constraint is unsatisfiable.",
            code=FEATURE_DEPENDENCY_MISSING,
            context={
                "component": parent,
                "child": child,
                "spec": spec,
                "found": child_version,
            },
        )


def _check_layering(parent: ComponentNode, child: ComponentNode) -> None:
    """Enforce the layering rule on a parent→child edge."""
    if child.layer > parent.layer:
        raise PluginError(
            f"Illegal upward dependency: component {parent.name!r} "
            f"(layer {parent.layer}) may not depend on {child.name!r} "
            f"(layer {child.layer}) — a dependency may only point at the same "
            "or a lower component layer.",
            code=FEATURE_CONTRACT_VIOLATION,
            context={
                "component": parent.name,
                "child": child.name,
                "parent_layer": parent.layer,
                "child_layer": child.layer,
            },
        )
    if parent.layer == 3 and child.layer == 3:
        raise PluginError(
            f"Layer-3 template {parent.name!r} may not depend on another "
            f"layer-3 template {child.name!r} (3→3 dependencies are disallowed).",
            code=FEATURE_CONTRACT_VIOLATION,
            context={"component": parent.name, "child": child.name},
        )


def _build_closure(
    selection: list[str], registry: dict[str, ComponentNode]
) -> dict[str, ComponentNode]:
    """Walk the transitive child closure, validating every edge."""
    needed: dict[str, ComponentNode] = {}
    stack = list(selection)
    while stack:
        name = stack.pop()
        if name in needed:
            continue
        node = registry.get(name)
        if node is None:
            raise PluginError(
                f"Component {name!r} is not registered.",
                code=FEATURE_DEPENDENCY_MISSING,
                context={"component": name},
            )
        if node.layer == 1 and node.children:
            raise PluginError(
                f"Layer-1 component {name!r} may not declare child components "
                f"({sorted(node.children)}); a basic component composes only a "
                "data contract.",
                code=FEATURE_CONTRACT_VIOLATION,
                context={"component": name, "children": sorted(node.children)},
            )
        needed[name] = node
        for child_name, spec in node.children.items():
            child = registry.get(child_name)
            if child is None:
                raise PluginError(
                    f"Component {name!r} depends on {child_name!r}, which is not registered.",
                    code=FEATURE_DEPENDENCY_MISSING,
                    context={"component": name, "child": child_name},
                )
            _version_satisfies(name, child_name, child.version, spec)
            _check_layering(node, child)
            stack.append(child_name)
    return needed


def _find_cycle_path(nodes: dict[str, ComponentNode]) -> list[str]:
    """DFS to recover one cycle as ``[a, b, ..., a]`` (closing repeat)."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(nodes, WHITE)
    path: list[str] = []

    def visit(name: str) -> list[str] | None:
        color[name] = GREY
        path.append(name)
        for child in nodes[name].children:
            if child not in nodes:
                continue
            if color[child] == GREY:
                return path[path.index(child) :] + [child]
            if color[child] == WHITE:
                found = visit(child)
                if found:
                    return found
        color[name] = BLACK
        path.pop()
        return None

    for name in sorted(nodes):
        if color[name] == WHITE:
            found = visit(name)
            if found:
                return found
    return []


def _topo_sort(nodes: dict[str, ComponentNode]) -> list[str]:
    """Kahn's algorithm: children before parents. Cycle → OPTIONS_DEP_CYCLE."""
    order: list[str] = []
    placed: set[str] = set()
    remaining = dict(nodes)
    while remaining:
        ready = sorted(
            name
            for name, node in remaining.items()
            if all(child in placed for child in node.children)
        )
        if not ready:
            raise OptionsError(
                f"Cyclic component dependency detected among: {', '.join(sorted(remaining))}.",
                code=OPTIONS_DEP_CYCLE,
                context={
                    "components": sorted(remaining),
                    "cycle_path": _find_cycle_path(remaining),
                },
            )
        for name in ready:
            order.append(name)
            placed.add(name)
            del remaining[name]
    return order


def _transitive_dependents(
    nodes: dict[str, ComponentNode],
) -> dict[str, frozenset[str]]:
    """``X -> {every component that transitively depends on X}``."""
    direct: dict[str, set[str]] = {name: set() for name in nodes}
    for parent, node in nodes.items():
        for child in node.children:
            if child in direct:
                direct[child].add(parent)

    dependents: dict[str, frozenset[str]] = {}
    for name in nodes:
        seen: set[str] = set()
        stack = list(direct[name])
        while stack:
            up = stack.pop()
            if up in seen:
                continue
            seen.add(up)
            stack.extend(direct.get(up, ()))
        dependents[name] = frozenset(seen)
    return dependents


def resolve_components(
    selection: list[str], registry: dict[str, ComponentNode]
) -> ResolvedComponents:
    """Resolve ``selection`` into an ordered plan + transitive dependents."""
    needed = _build_closure(selection, registry)
    order = _topo_sort(needed)
    dependents = _transitive_dependents(needed)

    contracts: set[str] = set()
    for node in needed.values():
        if node.contract:
            contracts.add(node.contract)
        contracts.update(node.aggregates)

    return ResolvedComponents(
        ordered=tuple(order),
        dependents=dependents,
        contracts=frozenset(contracts),
    )

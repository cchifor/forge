"""Fragment registry — name → :class:`Fragment` with one-shot freeze + audit.

The registry is mutable during plugin load (built-ins register at
import time, plugins extend at ``plugins.load_all`` time), then locked
via :meth:`_FragmentRegistry.freeze` so a late registration can't slip
past the audit. The audit catches the structural problems that would
otherwise surface deep inside generation:

1. Orphan ``depends_on`` — names that don't resolve. Hard error.
2. Orphan ``conflicts_with`` — warn (the intent is usually "if this
   ever gets added, we conflict"; not a typo worth failing on).
3. Conflict symmetry — warn when A→B but not B→A.
4. Toposort dry-run — Kahn's; cycle is a hard error with the cycle
   path surfaced for the author.
"""

from __future__ import annotations

import logging
from pathlib import Path

from forge.errors import (
    PLUGIN_COLLISION,
    PLUGIN_REGISTRY_FROZEN,
    FragmentError,
    PluginError,
)
from forge.fragments._spec import FRAGMENTS_DIRNAME, Fragment

logger = logging.getLogger(__name__)


class _FragmentRegistry(dict[str, Fragment]):
    """Registry dict with a one-shot ``freeze()`` + startup audit.

    Before ``freeze()`` — behaves like a regular dict. Built-ins and
    plugins register into it during module import and ``plugins.load_all``.
    After ``freeze()`` — mutations raise :class:`PluginError`
    (``PLUGIN_REGISTRY_FROZEN``) so a late registration doesn't slip past
    the audit. A clean ``freeze()`` call runs:

    1. **Orphan ``depends_on``** — every name in ``Fragment.depends_on``
       must resolve to a registered fragment. Hard error.
    2. **Orphan ``conflicts_with``** — if a fragment names a non-existent
       conflict, warn (the intent is usually "if this ever gets added,
       we conflict"; not a typo worth failing on).
    3. **Conflict symmetry** — ``conflicts_with`` is promoted to
       symmetric: if A declares conflict-with B but B doesn't declare
       conflict-with A, we *don't* silently mutate B (frozen dataclass);
       instead we warn so the author fixes it. Until Epic I+1 tightens
       this to a hard error, the resolver's symmetric check at
       ``capability_resolver._check_conflicts`` still catches both
       directions because it iterates every fragment's declared
       conflicts.
    4. **Toposort dry-run** — runs Kahn's algorithm over the full
       registry; any cycle is a hard error (``capability_resolver`` would
       hit it later, but catching at startup keeps stack traces short).

    The audit deliberately runs on the full registry rather than just on
    options-selected fragments — the set that resolves at any given
    generation is a subset, so whole-registry sanity is strictly
    stronger than per-plan validation.

    Tests that monkey-patch a fresh empty dict into the import sites
    (see ``tests/test_capability_resolver.py::isolated_registries``)
    bypass freezing entirely, which is correct — those tests swap the
    object, not mutate the real one.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.frozen: bool = False

    def __setitem__(self, key: str, value: Fragment) -> None:
        if self.frozen:
            raise PluginError(
                f"Cannot register fragment {key!r} — FRAGMENT_REGISTRY is "
                f"frozen. Late registration after plugin.load_all() is "
                f"rejected to keep the audit at startup a complete picture.",
                code=PLUGIN_REGISTRY_FROZEN,
                context={"fragment": key},
            )
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        if self.frozen:
            raise PluginError(
                f"Cannot delete fragment {key!r} — FRAGMENT_REGISTRY is frozen.",
                code=PLUGIN_REGISTRY_FROZEN,
                context={"fragment": key},
            )
        super().__delitem__(key)

    def freeze(self) -> None:
        """Run the registry audit, then lock the registry."""
        self._audit()
        self.frozen = True

    def _reset_for_tests(self) -> None:
        """Thaw + empty the registry; used by fixtures that swap in fakes."""
        self.frozen = False
        self.clear()

    # --- Audit passes -------------------------------------------------------

    def _audit(self) -> None:
        self._audit_orphan_depends_on()
        self._audit_orphan_conflicts()
        self._audit_conflict_symmetry()
        self._audit_no_cycles()

    def _audit_orphan_depends_on(self) -> None:
        for frag in self.values():
            missing = [d for d in frag.depends_on if d not in self]
            if missing:
                raise FragmentError(
                    f"Fragment {frag.name!r} depends_on unknown fragment(s): "
                    f"{sorted(missing)}. Registry out of sync — was a "
                    f"fragment removed or renamed without updating "
                    f"depends_on?",
                    context={"fragment": frag.name, "missing": sorted(missing)},
                )

    def _audit_orphan_conflicts(self) -> None:
        for frag in self.values():
            missing = [c for c in frag.conflicts_with if c not in self]
            if missing:
                # Not a hard error — "if this ever gets added, we conflict"
                # is a legitimate pattern for future-mutually-exclusive
                # fragments. Warn so the author notices typos.
                logger.warning(
                    "Fragment %r conflicts_with unknown fragment(s): %s",
                    frag.name,
                    sorted(missing),
                )

    def _audit_conflict_symmetry(self) -> None:
        for frag in self.values():
            for other in frag.conflicts_with:
                peer = self.get(other)
                if peer is None:
                    continue  # already warned in _audit_orphan_conflicts
                if frag.name not in peer.conflicts_with:
                    logger.warning(
                        "Fragment %r declares conflict with %r, but %r does "
                        "not declare conflict with %r. conflicts_with should "
                        "be symmetric — add %r to %r.conflicts_with.",
                        frag.name,
                        other,
                        other,
                        frag.name,
                        frag.name,
                        other,
                    )

    def _audit_no_cycles(self) -> None:
        """Kahn's algorithm dry-run over the full registry.

        On detection of a cycle, walks the dependency graph with a DFS
        to surface the actual cycle path (``a → b → c → a``) instead
        of just the unordered set of fragments involved. Plugin authors
        and built-in maintainers see exactly which edge to delete to
        break the cycle.
        """
        remaining = dict(self)
        order: set[str] = set()
        while remaining:
            ready = [
                name
                for name, frag in remaining.items()
                if all(dep in order for dep in frag.depends_on)
            ]
            if not ready:
                cyclic = sorted(remaining)
                cycle_path = self._find_cycle_path(remaining)
                if cycle_path:
                    arrow = " → ".join(cycle_path)
                    detail = f"cycle: {arrow}"
                else:
                    # Fallback when no concrete cycle could be derived
                    # (shouldn't happen — Kahn's guarantees a cycle when
                    # ``ready`` is empty + ``remaining`` is non-empty —
                    # but emit a useful message regardless).
                    detail = f"fragments involved: {cyclic}"
                raise FragmentError(
                    "Cyclic dependencies detected in FRAGMENT_REGISTRY — "
                    f"{detail}. Inspect ``depends_on`` entries in "
                    "fragments.py (or the offending plugin's "
                    "``api.add_fragment`` calls) and break one edge.",
                    context={
                        "cycle_among": cyclic,
                        "cycle_path": list(cycle_path) if cycle_path else [],
                    },
                )
            order.update(ready)
            for name in ready:
                del remaining[name]

    def _find_cycle_path(self, remaining: dict[str, Fragment]) -> list[str]:
        """DFS the depends_on graph to recover one concrete cycle path.

        Returns a list like ``["a", "b", "c", "a"]`` (the closing
        repetition makes the cycle visually obvious) or an empty list
        when the graph is acyclic from every entry point in ``remaining``.
        """
        # Cycle detection via colour-marked DFS. White → unvisited,
        # grey → on the current DFS stack, black → fully explored.
        WHITE, GREY, BLACK = 0, 1, 2
        colour: dict[str, int] = dict.fromkeys(remaining, WHITE)
        stack: list[str] = []

        def _visit(node: str) -> list[str] | None:
            colour[node] = GREY
            stack.append(node)
            frag = remaining.get(node)
            if frag is not None:
                for dep in frag.depends_on:
                    if dep not in remaining:
                        # Out-of-cycle dependency; ignore for cycle search.
                        continue
                    if colour[dep] == GREY:
                        # Back-edge — cycle from `dep` through `node`.
                        idx = stack.index(dep)
                        return stack[idx:] + [dep]
                    if colour[dep] == WHITE:
                        result = _visit(dep)
                        if result is not None:
                            return result
            stack.pop()
            colour[node] = BLACK
            return None

        for entry in sorted(remaining):
            if colour[entry] == WHITE:
                cycle = _visit(entry)
                if cycle is not None:
                    return cycle
        return []


FRAGMENT_REGISTRY: _FragmentRegistry = _FragmentRegistry()


def register_fragment(frag: Fragment) -> None:
    """Register a fragment. Raises on duplicate name or frozen registry."""
    if frag.name in FRAGMENT_REGISTRY:
        raise PluginError(
            f"Fragment {frag.name!r} is already registered",
            code=PLUGIN_COLLISION,
            context={"fragment": frag.name},
        )
    FRAGMENT_REGISTRY[frag.name] = frag


def fragments_root() -> Path:
    """Filesystem path to the _fragments root under forge/templates/."""
    # Resolve relative to the parent package (forge/) so this works
    # whether the caller invokes from the source tree or a wheel-installed
    # ``forge.fragments`` package.
    return Path(__file__).resolve().parent.parent / "templates" / FRAGMENTS_DIRNAME

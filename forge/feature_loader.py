"""Unified feature/plugin loader for forge.

Replaces the hardcoded import list in ``forge/features/__init__.py``
with a discovery-based approach:

1. Scan ``forge/features/*/feature.toml`` for built-in feature manifests.
2. Topologically sort features by ``[feature.depends]``.
3. Load each feature through ``ForgeAPI`` (same API as external plugins).
4. Load external plugins via entry points (existing mechanism).
5. Freeze registries and validate declared contracts.

The loaded-feature roster is captured in ``LOADED_FEATURES`` (module-level)
so introspection verbs can enumerate them after load.
"""

from __future__ import annotations

import importlib
import logging
from collections import deque
from pathlib import Path

from forge.api import ForgeAPI, PluginRegistration
from forge.errors import (
    FEATURE_CONTRACT_VIOLATION,
    FEATURE_DEPENDENCY_CYCLE,
    FEATURE_DEPENDENCY_MISSING,
    FragmentError,
    PluginError,
)
from forge.feature_manifest import (
    FeatureManifest,
    parse_feature_manifest,
    validate_manifest_contracts,
)
from forge.fragments import FRAGMENT_REGISTRY
from forge.options._registry import OPTION_REGISTRY

logger = logging.getLogger(__name__)

LOADED_FEATURES: list[FeatureManifest] = []


def load_all() -> list[FeatureManifest]:
    """Discover and load all features + plugins. Idempotent."""
    if LOADED_FEATURES:
        return LOADED_FEATURES

    # ------------------------------------------------------------------
    # 1. Discover internal features
    # ------------------------------------------------------------------
    features_dir = Path(__file__).resolve().parent / "features"
    manifests: list[FeatureManifest] = []
    for toml_path in sorted(features_dir.glob("*/feature.toml")):
        dir_name = toml_path.parent.name
        manifest = parse_feature_manifest(
            toml_path,
            module_path=f"forge.features.{dir_name}",
        )
        manifests.append(manifest)
        logger.debug("discovered feature %r (%s)", manifest.name, manifest.version)

    # ------------------------------------------------------------------
    # 2. Topological sort by depends
    # ------------------------------------------------------------------
    ordered = _topo_sort(manifests)

    # ------------------------------------------------------------------
    # 3. Load features in dependency order
    # ------------------------------------------------------------------
    for manifest in ordered:
        # Idempotency at the registry level: if this feature's declared
        # contract is already registered (e.g. a prior load populated the
        # registries while LOADED_FEATURES was reset out of sync), keep the
        # list consistent instead of re-registering — which would raise a
        # PLUGIN_COLLISION on the already-present options/fragments.
        if _already_registered(manifest):
            LOADED_FEATURES.append(manifest)
            continue

        mod = importlib.import_module(manifest.module_path)
        register_fn = getattr(mod, "register", None)
        if register_fn is None or not callable(register_fn):
            logger.warning(
                "feature %r at %s has no callable register(); skipping",
                manifest.name,
                manifest.module_path,
            )
            continue

        registration = PluginRegistration(
            name=manifest.name,
            module=manifest.module_path,
            version=manifest.version,
        )
        api = ForgeAPI(registration)
        try:
            register_fn(api)
        except Exception:
            logger.exception(
                "feature %r register() raised; aborting feature load",
                manifest.name,
            )
            raise

        LOADED_FEATURES.append(manifest)
        logger.debug("loaded feature %r", manifest.name)

    # ------------------------------------------------------------------
    # 4. Load external plugins (entry-point-based)
    # ------------------------------------------------------------------
    from forge.plugins import load_all as _load_plugins  # noqa: PLC0415

    _load_plugins()

    # ------------------------------------------------------------------
    # 5. Freeze registries
    # ------------------------------------------------------------------
    try:
        FRAGMENT_REGISTRY.freeze()
    except FragmentError as exc:
        from forge.plugins import FAILED_PLUGINS  # noqa: PLC0415

        FAILED_PLUGINS.append(("<registry audit>", f"{type(exc).__name__}: {exc}"))
        logger.error("FRAGMENT_REGISTRY audit failed: %s", exc)

    # ------------------------------------------------------------------
    # 6. Validate contracts (warn-only)
    # ------------------------------------------------------------------
    registered_options = frozenset(OPTION_REGISTRY.keys())
    registered_fragments = frozenset(FRAGMENT_REGISTRY.keys())
    for manifest in LOADED_FEATURES:
        violations = validate_manifest_contracts(
            manifest, registered_options, registered_fragments,
        )
        for msg in violations:
            logger.warning("contract violation (%s): %s", FEATURE_CONTRACT_VIOLATION, msg)

    return LOADED_FEATURES


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _already_registered(manifest: FeatureManifest) -> bool:
    """True if every option/fragment the manifest declares is already registered.

    A feature with an empty contract (no provides) is never considered
    already-registered, so it always runs its ``register()`` at least once.
    """
    if not manifest.provides_options and not manifest.provides_fragments:
        return False
    return all(o in OPTION_REGISTRY for o in manifest.provides_options) and all(
        f in FRAGMENT_REGISTRY for f in manifest.provides_fragments
    )


def _topo_sort(manifests: list[FeatureManifest]) -> list[FeatureManifest]:
    """Sort features by depends, raising on cycles or missing deps.

    Uses Kahn's algorithm: build an in-degree map from
    ``manifest.depends`` keys, seed the queue with zero-in-degree
    nodes, and drain. If the result is shorter than the input, a
    cycle exists.
    """
    by_name: dict[str, FeatureManifest] = {m.name: m for m in manifests}

    # Validate all declared dependencies exist in the discovered set.
    for m in manifests:
        for dep in m.depends:
            if dep not in by_name:
                raise PluginError(
                    f"Feature {m.name!r} depends on {dep!r} which was not discovered",
                    code=FEATURE_DEPENDENCY_MISSING,
                    context={"feature": m.name, "missing_dep": dep},
                )

    # Build adjacency + in-degree structures.
    in_degree: dict[str, int] = {name: 0 for name in by_name}
    dependents: dict[str, list[str]] = {name: [] for name in by_name}

    for m in manifests:
        for dep in m.depends:
            dependents[dep].append(m.name)
            in_degree[m.name] += 1

    # Seed queue with features that have no dependencies.
    queue: deque[str] = deque(
        name for name, degree in sorted(in_degree.items()) if degree == 0
    )

    ordered: list[FeatureManifest] = []
    while queue:
        name = queue.popleft()
        ordered.append(by_name[name])
        for dependent in sorted(dependents[name]):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(ordered) != len(manifests):
        remaining = sorted(set(by_name) - {m.name for m in ordered})
        raise PluginError(
            f"Dependency cycle among features: {', '.join(remaining)}",
            code=FEATURE_DEPENDENCY_CYCLE,
            context={"cycle_members": remaining},
        )

    return ordered


def reset_for_tests() -> None:
    """Clear loaded features state -- test-only."""
    LOADED_FEATURES.clear()

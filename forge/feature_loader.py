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

# Per-phase idempotency. ``LOADED_FEATURES`` is the introspection roster;
# ``_BUILTINS_LOADED`` is the fast-path guard for "the built-in discovery +
# register pass already ran in this process". They are distinct because
# ``load_all()`` must NOT early-return before the plugin-load + freeze
# phases just because built-ins are present — the built-ins are now
# registered at ``import forge`` time (see ``forge/__init__``), so a single
# ``if LOADED_FEATURES: return`` guard would skip plugins + freeze whenever
# the CLI/conftest later calls ``load_all()``.
_BUILTINS_LOADED: bool = False


def load_builtin_features() -> list[FeatureManifest]:
    """Discover and register the built-in features under ``forge/features/``.

    Idempotent via ``_BUILTINS_LOADED``. Does NOT load external plugins and
    does NOT freeze the registries — that orchestration lives in
    ``load_all()``. ``forge/__init__`` calls this at import so any
    programmatic consumer (``tests/matrix/runner.py``, library users) sees a
    populated ``OPTION_REGISTRY`` / ``FRAGMENT_REGISTRY`` without going
    through ``cli.main()``.
    """
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return LOADED_FEATURES

    # 1. Discover internal feature manifests.
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

    # 2. Topological sort by depends.
    ordered = _topo_sort(manifests)

    # 3. Register features in dependency order.
    for manifest in ordered:
        # Idempotency at the registry level: if this feature's declared
        # contract is already registered (e.g. a prior load populated the
        # registries while LOADED_FEATURES was reset out of sync), keep the
        # roster consistent instead of re-registering — which would raise a
        # PLUGIN_COLLISION on the already-present options/fragments.
        if _already_registered(manifest):
            if manifest not in LOADED_FEATURES:
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

    # Project the loaded manifests onto the component tier (layered-component
    # model). Components are features whose feature.toml sets [feature].layer;
    # this keeps COMPONENT_REGISTRY in sync with LOADED_FEATURES.
    from forge.components import (  # noqa: PLC0415
        populate_from_manifests,
        register_component_fragments,
    )

    populate_from_manifests(LOADED_FEATURES)
    # Register each component's emitter fragment into FRAGMENT_REGISTRY (still
    # unfrozen during built-in discovery) so a selected component's .vue files
    # are emitted by the existing file applier.
    register_component_fragments(LOADED_FEATURES)

    _BUILTINS_LOADED = True
    return LOADED_FEATURES


def load_all() -> list[FeatureManifest]:
    """Load built-ins + external plugins, then freeze + validate.

    Per-phase idempotent: each phase guards itself, so calling this after
    ``forge/__init__`` already ran ``load_builtin_features()`` still loads
    plugins and freezes the registry.
    """
    # Phase 1-3: built-in features (idempotent on _BUILTINS_LOADED).
    load_builtin_features()

    # Phase 4: external plugins (idempotent on plugins' own guards).
    from forge.plugins import load_all as _load_plugins  # noqa: PLC0415

    _load_plugins()

    # Phase 5: freeze the fragment registry — only once.
    if not FRAGMENT_REGISTRY.frozen:
        try:
            FRAGMENT_REGISTRY.freeze()
        except FragmentError as exc:
            from forge.plugins import FAILED_PLUGINS  # noqa: PLC0415

            FAILED_PLUGINS.append(("<registry audit>", f"{type(exc).__name__}: {exc}"))
            logger.error("FRAGMENT_REGISTRY audit failed: %s", exc)

    # Phase 6: validate manifest contracts (warn-only).
    registered_options = frozenset(OPTION_REGISTRY.keys())
    registered_fragments = frozenset(FRAGMENT_REGISTRY.keys())
    for manifest in LOADED_FEATURES:
        violations = validate_manifest_contracts(
            manifest,
            registered_options,
            registered_fragments,
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
    queue: deque[str] = deque(name for name, degree in sorted(in_degree.items()) if degree == 0)

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
    global _BUILTINS_LOADED
    LOADED_FEATURES.clear()
    _BUILTINS_LOADED = False

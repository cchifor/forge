"""Resolve a user's feature selections into an ordered, validated plan.

The resolver does four things:
    1. Apply `always_on` + `default_enabled` defaults to the user's selections.
    2. Topologically sort by `depends_on`, rejecting cycles.
    3. Reject conflicting features (two vector stores, two task queues, ...).
    4. Assert every enabled feature has an implementation for at least one
       backend in the project.

Output is consumed by `generator.generate` (ordered feature list for injection)
and `docker_manager.render_compose` (capability set for extra services).
"""

from __future__ import annotations

from dataclasses import dataclass

from forge.config import BackendLanguage, ProjectConfig
from forge.errors import GeneratorError
from forge.features import FEATURE_REGISTRY, FeatureConfig, FeatureSpec


@dataclass(frozen=True)
class ResolvedFeature:
    """A single feature, resolved to a concrete backend choice."""

    spec: FeatureSpec
    config: FeatureConfig
    # Backends (in project order) on which this feature will be applied.
    target_backends: tuple[BackendLanguage, ...]


@dataclass(frozen=True)
class ResolvedPlan:
    """Everything generator.py + docker_manager.py need to act on features."""

    ordered: tuple[ResolvedFeature, ...]
    capabilities: frozenset[str]


def _apply_defaults(
    selections: dict[str, FeatureConfig],
) -> dict[str, FeatureConfig]:
    """Merge registry defaults with user selections.

    - `always_on` features force `enabled=True` (user cannot turn them off here;
      that requires --disable-feature which mutates the dict *before* resolution).
    - `default_enabled` features turn on if the user hasn't touched them.
    - Unknown keys raise a clear error (typo catcher).
    """
    resolved: dict[str, FeatureConfig] = {}

    for key in selections:
        if key not in FEATURE_REGISTRY:
            known = ", ".join(sorted(FEATURE_REGISTRY)) or "(none registered)"
            raise GeneratorError(f"Unknown feature '{key}'. Known features: {known}")

    for key, spec in FEATURE_REGISTRY.items():
        user_cfg = selections.get(key)
        if spec.always_on:
            # always_on wins unless the caller explicitly disabled before us.
            enabled = True if user_cfg is None else user_cfg.enabled
        elif user_cfg is None:
            enabled = spec.default_enabled
        else:
            enabled = user_cfg.enabled
        options = dict(user_cfg.options) if user_cfg else {}
        resolved[key] = FeatureConfig(enabled=enabled, options=options)

    return resolved


def _topo_sort(enabled: dict[str, FeatureConfig]) -> list[str]:
    """Kahn's algorithm; raises on cycle or missing dependency."""
    remaining = set(enabled)
    order: list[str] = []

    # Validate dependencies up front for a better error message.
    for key in enabled:
        for dep in FEATURE_REGISTRY[key].depends_on:
            if dep not in enabled:
                raise GeneratorError(
                    f"Feature '{key}' requires '{dep}' but '{dep}' is not enabled. "
                    f"Enable it in the features: section or drop '{key}'."
                )

    while remaining:
        # Pick any feature whose deps are already in `order`.
        ready = [k for k in remaining if all(d in order for d in FEATURE_REGISTRY[k].depends_on)]
        if not ready:
            cyclic = ", ".join(sorted(remaining))
            raise GeneratorError(
                f"Cyclic feature dependency detected among: {cyclic}. "
                "Inspect `depends_on` entries in features.py."
            )
        # Sort by (FeatureSpec.order, key) for deterministic, priority-aware layering.
        ready.sort(key=lambda k: (FEATURE_REGISTRY[k].order, k))
        order.extend(ready)
        remaining.difference_update(ready)

    return order


def _check_conflicts(enabled_keys: set[str]) -> None:
    """Raise on any pair of enabled features with a conflicts_with relation."""
    for key in enabled_keys:
        spec = FEATURE_REGISTRY[key]
        for other in spec.conflicts_with:
            if other in enabled_keys:
                # Sort for a stable error message.
                a, b = sorted([key, other])
                raise GeneratorError(
                    f"Features '{a}' and '{b}' conflict and cannot both be enabled."
                )


def _target_backends(
    spec: FeatureSpec, project_backends: tuple[BackendLanguage, ...]
) -> tuple[BackendLanguage, ...]:
    """Backends in the project that this feature supports; preserves project order."""
    return tuple(lang for lang in project_backends if spec.supports(lang))


def resolve(config: ProjectConfig) -> ResolvedPlan:
    """Produce an ordered ResolvedPlan from `config.features`.

    Called from `ProjectConfig.validate()` and again (for the canonical instance)
    from `generator.generate`.
    """
    project_backends = tuple(bc.language for bc in config.backends)
    with_defaults = _apply_defaults(config.features)

    # Filter to the enabled set; always_on entries are already True.
    enabled = {k: cfg for k, cfg in with_defaults.items() if cfg.enabled}

    _check_conflicts(set(enabled))
    order = _topo_sort(enabled)

    resolved: list[ResolvedFeature] = []
    capabilities: set[str] = set()

    for key in order:
        spec = FEATURE_REGISTRY[key]
        targets = _target_backends(spec, project_backends)
        if not targets:
            # Silently skip a feature with no matching backend when it was
            # defaulted (always_on or default_enabled without user opt-in).
            # Only raise when the user *explicitly* enabled something that can't
            # apply anywhere — that's the misconfiguration worth surfacing.
            if spec.always_on or key not in config.features:
                continue
            supported = ", ".join(sorted(lang.value for lang in spec.implementations)) or "(none)"
            present = ", ".join(lang.value for lang in project_backends) or "(none)"
            raise GeneratorError(
                f"Feature '{key}' is enabled but none of its supported backends "
                f"({supported}) are present in this project (backends: {present})."
            )
        resolved.append(ResolvedFeature(spec=spec, config=enabled[key], target_backends=targets))
        capabilities.update(spec.capabilities)

    return ResolvedPlan(ordered=tuple(resolved), capabilities=frozenset(capabilities))

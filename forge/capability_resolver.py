"""Compile a ``ProjectConfig.options`` mapping into an ordered plan of
template fragments.

The resolver does four things:
    1. Apply Option defaults for every path the user didn't set.
    2. Translate each (path, value) into the fragment set via
       ``Option.enables[value]``.
    3. Topologically sort the fragments by ``Fragment.depends_on``.
    4. Reject conflicting fragments (two vector stores declared
       directly, for example — rare because Options usually ensure
       mutual exclusion by construction).

Output is a ``ResolvedPlan`` that downstream code (``generator``,
``feature_injector``, ``docker_manager``) already knows how to consume.
The plan's ``ordered`` sequence is stable across runs for a given config
so generation + re-application produce identical output.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge.config import BackendLanguage, ProjectConfig
from forge.errors import (
    OPTIONS_DEP_CYCLE,
    OPTIONS_FRAGMENT_CONFLICT,
    OPTIONS_INVALID_VALUE,
    OPTIONS_MISSING_FRAGMENT,
    OPTIONS_UNKNOWN_PATH,
    OptionsError,
)
from forge.fragments import FRAGMENT_REGISTRY, Fragment
from forge.options import OPTION_REGISTRY


@dataclass(frozen=True)
class ResolvedFragment:
    """A single fragment, resolved to a concrete set of target backends."""

    fragment: Fragment
    # Backends (in project order) on which this fragment will be applied.
    target_backends: tuple[BackendLanguage, ...]


@dataclass(frozen=True)
class ResolvedPlan:
    """The compiled output of ``resolve()``.

    ``ordered`` is the topologically-sorted list of fragments to apply.
    ``capabilities`` is the union of ``Fragment.capabilities`` across
    the plan — ``docker_manager.render_compose`` uses it to decide
    which extra services to provision (redis, qdrant, etc.).
    ``option_values`` is the fully-defaulted mapping of option path →
    value, useful for template context variables (e.g. rag.top_k).
    """

    ordered: tuple[ResolvedFragment, ...]
    capabilities: frozenset[str]
    option_values: dict[str, object]


# -----------------------------------------------------------------------------
# Back-compat alias: many downstream modules still iterate `plan.ordered`
# and access `rf.spec` / `rf.config` / `rf.target_backends`. Provide a
# shim so the feature_injector and generator keep working during the
# migration.
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedFeature:
    """Legacy shim. Mirrors the ResolvedFragment shape with the field names
    downstream code used to expect.
    """

    spec: Fragment  # historically FeatureSpec; Fragment has the fields the
    # injector actually reads (key→name, implementations, depends_on)
    target_backends: tuple[BackendLanguage, ...]

    @property
    def config(self) -> dict[str, object]:
        """Empty placeholder — previously carried FeatureConfig.options.
        Nothing in the codebase reads it post-refactor, but keeping the
        property lets existing test fixtures parse without attribute
        errors."""
        return {}


# -----------------------------------------------------------------------------
# Core resolve
# -----------------------------------------------------------------------------


def _apply_option_defaults(user_options: dict[str, object]) -> dict[str, object]:
    """Return a fully-defaulted option mapping.

    Every registered Option appears in the output; user values override
    defaults. Unknown keys in ``user_options`` raise — ProjectConfig's
    validator should have caught them earlier, but failing loudly here
    too keeps the pipeline safe.
    """
    for path in user_options:
        if path not in OPTION_REGISTRY:
            known = ", ".join(sorted(OPTION_REGISTRY)) or "(none registered)"
            raise OptionsError(
                f"Unknown option '{path}'. Known options: {known}",
                code=OPTIONS_UNKNOWN_PATH,
                context={"path": path},
            )

    resolved: dict[str, object] = {}
    for path, opt in OPTION_REGISTRY.items():
        resolved[path] = user_options.get(path, opt.default)
    return resolved


def _collect_fragments(option_values: dict[str, object]) -> set[str]:
    """Compile options' ``enables`` maps into a flat set of fragment names."""
    fragments: set[str] = set()
    for path, value in option_values.items():
        spec = OPTION_REGISTRY[path]
        fragments.update(spec.enables.get(value, ()))
    return fragments


def _expand_deps(fragment_set: set[str]) -> set[str]:
    """Pull every transitive dep into the fragment set.

    ``Fragment.depends_on`` is a tuple of fragment names. If a fragment
    is in the plan, so must its deps be — users never see these, so
    we auto-include transparently (no error).
    """
    added = True
    while added:
        added = False
        for name in list(fragment_set):
            spec = FRAGMENT_REGISTRY.get(name)
            if spec is None:
                raise OptionsError(
                    f"Option references unknown fragment '{name}'. Registry "
                    "out of sync — did you rename a fragment directory without "
                    "updating options.py?",
                    code=OPTIONS_MISSING_FRAGMENT,
                    context={"fragment": name},
                )
            for dep in spec.depends_on:
                if dep not in fragment_set:
                    fragment_set.add(dep)
                    added = True
    return fragment_set


def _topo_sort(fragment_names: set[str]) -> list[str]:
    """Kahn's algorithm over Fragment.depends_on.

    Sorts ``ready`` sets by (Fragment.order, name) so middleware
    layering is deterministic across runs.
    """
    remaining = set(fragment_names)
    order: list[str] = []

    while remaining:
        ready = [
            name
            for name in remaining
            if all(dep in order for dep in FRAGMENT_REGISTRY[name].depends_on)
        ]
        if not ready:
            cyclic = ", ".join(sorted(remaining))
            raise OptionsError(
                f"Cyclic fragment dependency detected among: {cyclic}. "
                "Inspect `depends_on` entries in fragments.py.",
                code=OPTIONS_DEP_CYCLE,
                context={"fragments": sorted(remaining)},
            )
        ready.sort(key=lambda n: (FRAGMENT_REGISTRY[n].order, n))
        order.extend(ready)
        remaining.difference_update(ready)
    return order


def _check_conflicts(fragment_names: set[str]) -> None:
    for name in fragment_names:
        spec = FRAGMENT_REGISTRY[name]
        for other in spec.conflicts_with:
            if other in fragment_names:
                a, b = sorted([name, other])
                raise OptionsError(
                    f"Fragments '{a}' and '{b}' conflict and cannot both be enabled.",
                    code=OPTIONS_FRAGMENT_CONFLICT,
                    context={"fragments": [a, b]},
                )


def _target_backends(
    frag: Fragment, project_backends: tuple[BackendLanguage, ...]
) -> tuple[BackendLanguage, ...]:
    """Backends in the project that this fragment supports; project order."""
    return tuple(lang for lang in project_backends if frag.supports(lang))


def resolve(config: ProjectConfig) -> ResolvedPlan:
    """Produce an ordered ResolvedPlan from ``config.options``.

    Called from ``ProjectConfig.validate()`` (eager validation) and
    again from ``generator.generate`` (canonical instance consumed by
    the injector).
    """
    project_backends = tuple(bc.language for bc in config.backends)

    option_values = _apply_option_defaults(config.options)
    fragment_set = _collect_fragments(option_values)
    fragment_set = _expand_deps(fragment_set)
    _check_conflicts(fragment_set)
    order = _topo_sort(fragment_set)

    resolved: list[ResolvedFragment] = []
    capabilities: set[str] = set()

    for name in order:
        frag = FRAGMENT_REGISTRY[name]
        targets = _target_backends(frag, project_backends)
        if not targets:
            # A fragment was pulled in (via option value or transitive
            # dep) but none of the project's backends support it. If the
            # user explicitly asked for the fragment (via an option
            # whose value maps to it), that's a hard error — they wanted
            # something that can't apply. If the fragment was pulled in
            # by a default Option value (they didn't touch it), skip
            # silently — that's just "this default isn't relevant here".
            if _is_user_selected(config.options, name):
                supported = ", ".join(sorted(lg.value for lg in frag.implementations)) or "(none)"
                present = ", ".join(lang.value for lang in project_backends) or "(none)"
                raise OptionsError(
                    f"Fragment '{name}' is requested but none of its supported "
                    f"backends ({supported}) are present in this project "
                    f"(backends: {present}).",
                    code=OPTIONS_INVALID_VALUE,
                    context={
                        "fragment": name,
                        "supported_backends": sorted(lg.value for lg in frag.implementations),
                        "project_backends": [lang.value for lang in project_backends],
                    },
                )
            continue
        resolved.append(ResolvedFragment(fragment=frag, target_backends=targets))
        capabilities.update(frag.capabilities)

    return ResolvedPlan(
        ordered=tuple(resolved),
        capabilities=frozenset(capabilities),
        option_values=option_values,
    )


def _is_user_selected(user_options: dict[str, object], fragment_name: str) -> bool:
    """True if any option the user explicitly set enables this fragment.

    Used to distinguish "silent skip — default didn't apply here" from
    "hard error — user requested something impossible."
    """
    for path, value in user_options.items():
        spec = OPTION_REGISTRY.get(path)
        if spec is None:
            continue
        if fragment_name in spec.enables.get(value, ()):
            return True
    return False

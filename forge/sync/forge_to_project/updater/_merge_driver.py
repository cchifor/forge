"""Three-way merge orchestration — apply fragment plans to backends.

Split out from the original ``updater.py`` god module — see
:mod:`forge.sync.forge_to_project.updater` for the public surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from forge.capability_resolver import ResolvedFragment
from forge.config import BackendConfig
from forge.fragment_context import FragmentContext, UpdateMode
from forge.sync.provenance import ProvenanceCollector

if TYPE_CHECKING:
    from forge.config import FrontendFramework
    from forge.fragments import FragmentImplSpec
    from forge.middleware_spec import MiddlewareSpec


def apply_features(
    bc: BackendConfig,
    backend_dir: Path,
    resolved: tuple[ResolvedFragment, ...],
    quiet: bool = False,
    *,
    update_mode: UpdateMode = "strict",
    file_baselines: Mapping[str, str] | None = None,
    collector: ProvenanceCollector | None = None,
    option_values: Mapping[str, Any] | None = None,
    project_root: Path | None = None,
) -> None:
    """Apply each backend-scoped fragment that supports this backend.

    Project-scoped fragments are emitted separately via
    ``apply_project_features`` after all backends are rendered.

    ``update_mode`` (P0.1, 1.1.0-alpha.2) drives the file-copy collision
    behaviour. ``"strict"`` is fresh generation — fragments may not
    overlap the base template or each other. ``"merge"`` / ``"skip"`` /
    ``"overwrite"`` are the three ``forge --update`` modes; see
    :data:`forge.fragment_context.UpdateMode`.

    ``file_baselines`` is the manifest's per-file baseline SHA map
    (POSIX rel-path → SHA-256). Required by ``"merge"`` mode for the
    three-way decision; ignored by the other modes.

    When ``collector`` is supplied, every file written by the fragment
    layer is recorded in the provenance manifest with ``origin='fragment'``
    and the fragment's name.

    ``option_values`` (Epic E, 1.1.0-alpha.1) — the resolver's fully-
    defaulted option map. When provided, each fragment's
    :class:`FragmentContext` sees a filtered view restricted to the
    impl's ``reads_options`` tuple. When omitted (backward-compat for
    callers that haven't threaded the plan through yet), fragments see
    ``ctx.options == {}`` — the pre-Epic-E behaviour.

    ``project_root`` is needed for merge-zone injections and future
    provenance-driven uninstall. Defaults to ``backend_dir.parent.parent``
    on the assumption of the conventional ``<project_root>/services/<backend>/``
    layout — the generator always passes it explicitly.
    """
    if option_values is None:
        option_values = {}
    if project_root is None:
        project_root = backend_dir.parent.parent
    for rf in resolved:
        if bc.language not in rf.target_backends:
            continue
        impl = rf.fragment.implementations[bc.language]
        if impl.scope != "backend":
            continue
        if not quiet:
            print(f"  [frag] applying '{rf.fragment.name}' to {bc.name} ({bc.language.value})")
        ctx = FragmentContext.filtered(
            backend_config=bc,
            backend_dir=backend_dir,
            project_root=project_root,
            option_values=option_values,
            reads_options=impl.reads_options,
            provenance=collector,
            update_mode=update_mode,
            file_baselines=file_baselines,
        )
        _apply_fragment(ctx, impl, rf.fragment.name, middlewares=rf.fragment.middlewares)


def apply_project_features(
    project_root: Path,
    resolved: tuple[ResolvedFragment, ...],
    quiet: bool = False,
    *,
    update_mode: UpdateMode = "strict",
    file_baselines: Mapping[str, str] | None = None,
    collector: ProvenanceCollector | None = None,
    option_values: Mapping[str, Any] | None = None,
    frontend_framework: FrontendFramework | None = None,
) -> None:
    """Apply project-scoped fragment implementations at the project root.

    See :func:`apply_features` for ``update_mode``, ``file_baselines``,
    and ``option_values`` semantics.

    ``frontend_framework`` (when provided) gates fragments whose
    ``target_frontends`` tuple is non-empty: a fragment that declares
    ``target_frontends=(FrontendFramework.VUE,)`` only applies when the
    project's frontend is Vue. Pass ``FrontendFramework.NONE`` for
    frontend-less projects so frontend-targeted fragments skip
    explicitly. Pass ``None`` (the default) when the caller doesn't yet
    track frontend choice (the updater path) — gating becomes a no-op
    in that case so existing behavior is preserved until the caller is
    wired through.
    """
    if option_values is None:
        option_values = {}
    for rf in resolved:
        if (
            frontend_framework is not None
            and rf.fragment.target_frontends
            and frontend_framework not in rf.fragment.target_frontends
        ):
            if not quiet:
                print(
                    f"  [frag] skipping '{rf.fragment.name}' — "
                    f"target_frontends={[f.value for f in rf.fragment.target_frontends]}, "
                    f"project frontend={frontend_framework.value}"
                )
            continue
        for lang in rf.target_backends:
            impl = rf.fragment.implementations[lang]
            if impl.scope == "project":
                if not quiet:
                    print(f"  [frag] applying '{rf.fragment.name}' to project root")
                proxy = BackendConfig(name="project", project_name="", language=lang)
                ctx = FragmentContext.filtered(
                    backend_config=proxy,
                    backend_dir=project_root,
                    project_root=project_root,
                    option_values=option_values,
                    reads_options=impl.reads_options,
                    provenance=collector,
                    update_mode=update_mode,
                    file_baselines=file_baselines,
                )
                # Project-scope fragments typically don't declare middlewares
                # (they emit project-level files like AGENTS.md). Pass the
                # tuple anyway so the pipeline API stays uniform.
                _apply_fragment(ctx, impl, rf.fragment.name, middlewares=rf.fragment.middlewares)
                break


def _apply_fragment(
    ctx: FragmentContext,
    impl: FragmentImplSpec,
    feature_key: str,
    *,
    middlewares: tuple[MiddlewareSpec, ...] = (),
) -> None:
    """Apply one fragment implementation via the default :class:`FragmentPipeline`.

    Epic A lands the applier decomposition: four single-responsibility
    classes composed by :class:`FragmentPipeline`. Epic K threads any
    :class:`MiddlewareSpec` declarations on the fragment into the plan
    so the applier emits the middleware import + registration lines
    without a handwritten ``inject.yaml``.

    This function is a stable internal entry point — callers route
    through it so the rest of the package doesn't need to know
    pipelines exist.
    """
    from forge.appliers import FragmentPipeline  # noqa: PLC0415

    FragmentPipeline.default().run(ctx, impl, feature_key, middlewares=middlewares)

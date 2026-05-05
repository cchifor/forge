"""Fragment *plan* — the typed record of what a fragment will mutate.

``FragmentPlan.from_impl`` resolves a :class:`FragmentImplSpec` against
disk + the current :class:`FragmentContext` and produces a frozen record
of every file to copy, every injection to apply, every dep to add, and
every env var to append. Appliers consume the plan without reaching
back into the filesystem.

The separation makes dry-run + provenance-driven uninstall
(Epic F) natural: reusing the same plan against an "inverse" applier
deletes what a forward applier would have written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from forge.errors import FRAGMENT_DIR_MISSING, FragmentError

if TYPE_CHECKING:
    from forge.config import BackendLanguage
    from forge.feature_injector import _Injection
    from forge.fragments import FragmentImplSpec
    from forge.middleware_spec import MiddlewareSpec


@dataclass(frozen=True)
class FragmentPlan:
    """What a fragment implementation will mutate.

    Attributes:
        fragment_dir: Absolute path on disk. Either under
            ``forge/templates/_fragments/`` for built-ins or under a
            plugin's own package for plugin fragments.
        files_dir: ``fragment_dir / "files"`` when it exists; ``None`` for
            inject-only fragments.
        injections: Parsed + rendered ``inject.yaml`` entries. Empty
            tuple when the fragment has no ``inject.yaml``.
        dependencies: Pass-through of ``impl.dependencies``.
        env_vars: Pass-through of ``impl.env_vars``.
        feature_key: Fragment name used in BEGIN/END sentinels + as
            the provenance ``fragment_name`` tag.
    """

    fragment_dir: Path
    files_dir: Path | None
    injections: tuple[_Injection, ...]
    dependencies: tuple[str, ...]
    env_vars: tuple[tuple[str, str], ...]
    feature_key: str

    @classmethod
    def from_impl(
        cls,
        impl: FragmentImplSpec,
        feature_key: str,
        *,
        options: Mapping[str, Any] | None = None,
        middlewares: tuple[MiddlewareSpec, ...] = (),
        backend: BackendLanguage | None = None,
    ) -> FragmentPlan:
        """Resolve an impl to a concrete plan.

        ``options`` (default empty) seeds Jinja rendering for injection
        entries that set ``render: true`` in ``inject.yaml``. The
        resolver has already validated that every path the impl
        declares in ``reads_options`` exists in the registry.

        ``middlewares`` + ``backend`` (Epic K, 1.1.0-alpha.1) let the
        applier expand :class:`MiddlewareSpec` declarations into
        ``_Injection`` records using the per-backend renderer. Specs
        whose ``backend`` doesn't match are silently dropped, so one
        fragment can carry specs for every backend it supports.
        Synth'd injections are appended after ``inject.yaml`` ones;
        they share the same zoned-dispatch pipeline downstream.
        """
        # Lazy imports to avoid a circular: feature_injector imports
        # from forge.appliers at module-load time post-Epic-A.
        from forge.feature_injector import (  # noqa: PLC0415
            _load_injections,
            _resolve_fragment_dir,
        )
        from forge.middleware_spec import (  # noqa: PLC0415
            render_middleware_injections,
        )

        fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
        if not fragment_dir.is_dir():
            raise FragmentError(
                f"Fragment directory not found: {fragment_dir}. "
                "Check FragmentImplSpec.fragment_dir in fragments.py.",
                code=FRAGMENT_DIR_MISSING,
                context={
                    "fragment_dir": str(fragment_dir),
                    "fragment_impl_key": impl.fragment_dir,
                },
            )

        files_path = fragment_dir / "files"
        files_dir: Path | None = files_path if files_path.is_dir() else None

        inject_path = fragment_dir / "inject.yaml"
        if inject_path.is_file():
            yaml_injections = tuple(
                _load_injections(inject_path, feature_key, options=options or {})
            )
        else:
            yaml_injections = ()

        synth_injections: tuple[_Injection, ...] = ()
        if middlewares and backend is not None:
            synth_injections = render_middleware_injections(middlewares, backend, feature_key)

        return cls(
            fragment_dir=fragment_dir,
            files_dir=files_dir,
            injections=yaml_injections + synth_injections,
            dependencies=impl.dependencies,
            env_vars=impl.env_vars,
            feature_key=feature_key,
        )

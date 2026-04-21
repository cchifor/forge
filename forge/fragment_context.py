"""Context object threaded through fragment application (Epic E, 1.1.0-alpha.1).

Before Epic E, ``feature_injector._apply_fragment`` took four loose
positional arguments (``bc, backend_dir, impl, options={}``) and the
``options`` dict was always empty — fragments couldn't branch on the
user-resolved option values without shipping one fragment per value.

:class:`FragmentContext` bundles everything a fragment needs at apply
time into one immutable record, and exposes ``options`` as a *filtered*
view — only the paths declared in ``FragmentImplSpec.reads_options`` are
visible. A fragment can't silently depend on an option it didn't
declare; the resolver validates the declared paths against
``OPTION_REGISTRY`` at resolve time, so typos surface before generation.

This file is intentionally thin — the heavy lifting (construction,
dispatch into appliers) lives in ``feature_injector``. Epic A's applier
decomposition uses this same ``FragmentContext`` as its sole input.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from forge.config import BackendConfig
    from forge.provenance import ProvenanceCollector


@dataclass(frozen=True)
class FragmentContext:
    """Immutable per-fragment context handed to every applier.

    ``backend_config`` identifies the target backend (language, ports,
    feature flags). For project-scope fragments, the generator passes a
    synthetic proxy ``BackendConfig(name="project", ...)``.

    ``backend_dir`` is where backend-scope fragments emit files +
    injections. ``project_root`` is the generated project's top-level
    directory; most fragments don't need it, but the merge-zone injector
    and any future uninstaller do.

    ``options`` is a *filtered* read-only view of the resolver's
    ``option_values`` — only paths listed in ``impl.reads_options``
    appear. A fragment that declares ``reads_options=("rag.top_k",)``
    sees ``{"rag.top_k": 5}``; it has no access to other paths even
    though they're in the resolver's full dict.

    ``provenance`` is ``None`` during dry-runs and during the synthetic
    unit-test path; production generation always sets it.

    ``skip_existing_files=True`` is the ``forge --update`` semantics —
    fragment file copies that land on a pre-existing path skip silently
    rather than raising.
    """

    backend_config: BackendConfig
    backend_dir: Path
    project_root: Path
    options: Mapping[str, Any]
    provenance: ProvenanceCollector | None
    skip_existing_files: bool = False

    @classmethod
    def filtered(
        cls,
        *,
        backend_config: BackendConfig,
        backend_dir: Path,
        project_root: Path,
        option_values: Mapping[str, Any],
        reads_options: tuple[str, ...],
        provenance: ProvenanceCollector | None = None,
        skip_existing_files: bool = False,
    ) -> FragmentContext:
        """Build a context where ``options`` contains only ``reads_options``.

        The resolver has already validated that every path in
        ``reads_options`` exists in ``OPTION_REGISTRY`` and therefore in
        ``option_values``. If a caller hands us a path not in
        ``option_values`` (e.g. a synthetic test fixture) we silently
        drop it — the alternative would be to raise during generation,
        which defeats the "catch early" purpose of the resolver pass.
        """
        options = {
            path: option_values[path]
            for path in reads_options
            if path in option_values
        }
        return cls(
            backend_config=backend_config,
            backend_dir=backend_dir,
            project_root=project_root,
            options=options,
            provenance=provenance,
            skip_existing_files=skip_existing_files,
        )

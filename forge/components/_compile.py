"""Compile a component into the existing option/fragment graph (Phase 3).

This is the bridge from the component *tier* down to the fragment graph the
generator already knows how to apply. A component's emitter becomes a
**project-scoped** fragment gated on the target frontend — the same shape
``features/auth`` / ``features/platform`` use to ship ``.vue`` files. The
fragment's ``depends_on`` mirrors the component's children (each child compiles
to its own ``component_<Name>`` fragment), so the existing topo-sort applies a
component after the children it composes.

No new emission engine: the produced ``Fragment`` flows through the existing
``copy_files`` / injection appliers and the provenance/merge path.
"""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from pathlib import Path

from forge.components._registry import component_node_from_manifest
from forge.components._spec import ComponentNode
from forge.config import BackendLanguage, FrontendFramework
from forge.feature_manifest import FeatureManifest
from forge.fragments import Fragment, FragmentImplSpec

# Component emitter templates live here, under the fragment template tree so the
# file appliers resolve them like any other fragment. ``<root>/<Name>/all``
# holds the framework-agnostic emit (the per-framework split lives inside).
COMPONENT_TEMPLATES_ROOT = (
    Path(__file__).resolve().parent.parent / "templates" / "_fragments" / "components"
)


def component_fragment_name(component: str) -> str:
    """The fragment name a component compiles to (``component_<Name>``)."""
    return f"component_{component}"


def component_fragments(
    node: ComponentNode,
    *,
    frontend: FrontendFramework = FrontendFramework.VUE,
    templates_root: Path | None = None,
) -> tuple[Fragment, ...]:
    """Compile one component into its emitter fragment(s).

    Returns a single project-scoped fragment named ``component_<Name>`` that:
    - is gated on ``frontend`` via ``target_frontends`` (Vue only, for now);
    - registers a lone ``BackendLanguage.PYTHON`` impl (the dataclass requires a
      non-empty implementations map — the proxy-backend project applier handles
      it; mirrors ``features/auth``'s frontend fragments);
    - depends on each child's ``component_<Child>`` fragment so the topo-sort
      applies children first.
    """
    root = templates_root or COMPONENT_TEMPLATES_ROOT
    # Dir name mirrors the fragment name (component_<Name>), matching the
    # ``templates/<fragment_name>/<lang>`` convention features/auth uses.
    fragment_dir = str(root / component_fragment_name(node.name) / "all")
    impl = FragmentImplSpec(fragment_dir=fragment_dir, scope="project")
    fragment = Fragment(
        name=component_fragment_name(node.name),
        implementations={BackendLanguage.PYTHON: impl},
        depends_on=tuple(component_fragment_name(c) for c in sorted(node.children)),
        target_frontends=(frontend,),
        # RFC-011 opt-out: the layered model ships Vue emitters first; Svelte +
        # Flutter component emitters follow once the model is proven (plan §H).
        frontend_skip_reason=(
            "Layered-component model is Vue-first; Svelte/Flutter component "
            "emitters follow once the model is proven."
        ),
    )
    return (fragment,)


def register_component_fragments(
    manifests: Iterable[FeatureManifest],
    *,
    registry: MutableMapping[str, Fragment] | None = None,
    frontend: FrontendFramework = FrontendFramework.VUE,
) -> list[str]:
    """Register each component manifest's emitter fragment into the registry.

    The emitter template dir is derived from the manifest location
    (``<feature dir>/templates/component_<Name>/all``), so a component ships
    its ``.vue``/``.ts`` files alongside its ``feature.toml`` like any other
    feature. Called by the loader once during built-in feature discovery (while
    FRAGMENT_REGISTRY is unfrozen). Idempotent: skips names already present.
    Returns the fragment names registered this call.
    """
    if registry is None:
        from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

        registry = FRAGMENT_REGISTRY

    registered: list[str] = []
    for manifest in manifests:
        if manifest.component_layer is None:
            continue
        node = component_node_from_manifest(manifest)
        templates_root = Path(manifest.manifest_path).parent / "templates"
        for frag in component_fragments(node, frontend=frontend, templates_root=templates_root):
            if frag.name in registry:
                continue
            registry[frag.name] = frag
            registered.append(frag.name)
    return registered

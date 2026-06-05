"""UI app-shell layout variants — the selectable ``--layout`` templates.

This is deliberately **separate** from :mod:`forge.frontends`
(:class:`~forge.frontends.FrontendLayout`), which records a framework's
per-file *codegen emit paths*. A ``LayoutVariant`` records which Copier
*template* renders a given ``(framework, layout)`` pair — the user-facing
visual shell chosen via ``--layout`` / ``FrontendConfig.layout``.

Composition model (Layer 1 → 2 → 3): a layout (Layer-3) is a *thin* shell
that composes reusable Layer-2 region components (AppHeader, SidebarNav,
BottomTabBar, …) built from Layer-1 basics. The reusable components live in
the shared base template; a variant supplies only its shell skeleton.
``base_template_dir`` names that shared base — when set, the generator
renders the base first then overlays the variant (two-stage render, proven
byte-identical to a single render in the Phase-0 PoC). An empty
``base_template_dir`` means the variant is self-contained (single render) —
how the built-in ``sidebar`` baseline ships.

**Discovery.** Variants are auto-discovered from manifest files at
``forge/templates/layouts/<framework>/<name>/layout.toml`` (mirroring the
feature-discovery pattern). Adding a layout is a drop-in: ship a manifest +
its overlay template; no code change here. Plugins can also register at
runtime via :meth:`forge.api.ForgeAPI.add_frontend_layout`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from forge.config import FrontendFramework

if TYPE_CHECKING:
    from forge.config import _PluginFramework

    # Registry key: a built-in framework or a plugin-registered one.
    FrameworkKey = FrontendFramework | _PluginFramework

#: The default layout — today's single per-framework shell. Selecting it
#: reproduces pre-layouts output byte-for-byte (golden gate).
DEFAULT_LAYOUT = "sidebar"

#: Root of the layout-manifest tree (``layouts/<framework>/<name>/layout.toml``).
_LAYOUTS_ROOT = Path(__file__).parent / "templates" / "layouts"


@dataclass(frozen=True)
class LayoutVariant:
    """One selectable ``(framework, layout)`` app-shell template.

    Attributes:
        framework: The frontend framework this variant targets.
        name: The layout slug (e.g. ``"sidebar"``, ``"topnav"``) — the
            ``--layout`` value.
        template_dir: The variant's Copier template, **relative to
            ``forge/templates``** (e.g. ``"layouts/vue/topnav"``). For a
            self-contained variant this is the whole template; for a
            two-stage variant it is the thin shell overlay.
        display_label: Human-readable name for CLI/interactive listings.
        supported: ``False`` hides the variant from selection without
            unregistering it.
        base_template_dir: Optional shared-base template (relative path)
            rendered *before* ``template_dir`` overlays it. Empty ⇒
            self-contained single render.
    """

    framework: FrameworkKey
    name: str
    template_dir: str
    display_label: str
    supported: bool = True
    base_template_dir: str = ""


LAYOUT_VARIANTS: dict[tuple[FrameworkKey, str], LayoutVariant] = {}

_FRAMEWORK_BY_VALUE = {f.value: f for f in FrontendFramework}


def register_layout_variant(variant: LayoutVariant) -> None:
    """Register a :class:`LayoutVariant`. Raises on a duplicate key."""
    key = (variant.framework, variant.name)
    if key in LAYOUT_VARIANTS:
        raise ValueError(
            f"LayoutVariant {_fw_value(variant.framework)}/{variant.name!r} is already registered"
        )
    LAYOUT_VARIANTS[key] = variant


def get_layout_variant(framework: FrameworkKey, name: str) -> LayoutVariant | None:
    """Return the variant for ``(framework, name)``, or ``None``."""
    return LAYOUT_VARIANTS.get((framework, name))


def available_layouts(framework: FrameworkKey) -> tuple[str, ...]:
    """Return the sorted, *supported* layout slugs for ``framework``."""
    return tuple(
        sorted(name for (fw, name), v in LAYOUT_VARIANTS.items() if fw == framework and v.supported)
    )


def all_layout_names() -> tuple[str, ...]:
    """Return every registered layout slug across frameworks (sorted, deduped)."""
    return tuple(sorted({name for (_fw, name) in LAYOUT_VARIANTS}))


def _fw_value(framework: FrameworkKey) -> str:
    return getattr(framework, "value", str(framework))


def _framework_from_value(value: str) -> FrameworkKey | None:
    """Resolve a manifest's ``framework`` string to a framework key.

    Returns ``None`` for an unknown value so discovery can skip a stray
    manifest rather than raising at import time.
    """
    builtin = _FRAMEWORK_BY_VALUE.get(value)
    if builtin is not None:
        return builtin
    # A plugin framework may not be registered yet at discovery time; only
    # resolve to one that already exists.
    from forge.config import PLUGIN_FRAMEWORKS, resolve_frontend_framework  # noqa: PLC0415

    if value in PLUGIN_FRAMEWORKS:
        return resolve_frontend_framework(value)
    return None


def _discover() -> None:
    """Discover built-in variants from ``layouts/<fw>/<name>/layout.toml``."""
    if not _LAYOUTS_ROOT.is_dir():
        return
    for manifest in sorted(_LAYOUTS_ROOT.glob("*/*/layout.toml")):
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        layout = data.get("layout")
        if not isinstance(layout, dict):
            continue
        name = layout.get("name")
        fw_value = layout.get("framework")
        template_dir = layout.get("template_dir")
        if not name or not fw_value or not template_dir:
            continue
        framework = _framework_from_value(str(fw_value))
        if framework is None:
            continue
        register_layout_variant(
            LayoutVariant(
                framework=framework,
                name=str(name),
                template_dir=str(template_dir),
                display_label=str(layout.get("display_label", name)),
                supported=bool(layout.get("supported", True)),
                base_template_dir=str(layout.get("base", "")),
            )
        )


def _reset_for_tests() -> None:
    """Clear the registry and re-discover built-ins (test isolation)."""
    LAYOUT_VARIANTS.clear()
    _discover()


_discover()

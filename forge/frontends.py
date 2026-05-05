"""Per-frontend layout registry (Epic O, 1.1.0-alpha.1).

Before Epic O, ``forge/codegen/pipeline.py`` hardcoded per-framework
paths in three ``if/elif`` ladders — one for UI protocol types, one for
the canvas manifest, one for shared enums. Adding a fourth frontend
meant touching every ladder and remembering which emitter writes which
file extension. The hardcoding was also a documentation gap: the only
place to answer "where does Svelte's canvas manifest land?" was to
grep the pipeline.

:class:`FrontendLayout` collects a framework's emit paths + its
preferred emitter flavours (TS vs. Dart) into one frozen record.
:data:`FRONTEND_LAYOUTS` maps each built-in ``FrontendFramework`` to
its layout; the pipeline is now one loop over the layout rather than
three per-framework branches.

Plugin-added frontends land in the registry via
``register_frontend_layout(layout)``. That's the only API they need —
once a layout is present, the codegen pipeline picks them up
automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge.config import FrontendFramework

EmitterFlavour = Literal["typescript", "dart"]


@dataclass(frozen=True)
class FrontendLayout:
    """Per-frontend emit paths + emitter flavour choices.

    All paths are relative to the frontend's root directory (e.g.
    ``apps/frontend/`` for Vue/Svelte, ``apps/flutter-frontend/`` for
    Flutter). The pipeline joins them with ``project_root /
    config.frontend_slug`` to get the final destination.

    Attributes:
        framework: The ``FrontendFramework`` enum value this layout
            describes. Used as the registry key.
        ui_protocol_path: Where the generated UI-protocol type file
            lands. Includes filename + extension.
        ui_protocol_emitter: ``"typescript"`` (emit ``.ts``) or
            ``"dart"`` (emit ``.dart``) — determines which
            :mod:`forge.codegen.ui_protocol` emitter the pipeline
            calls.
        canvas_manifest_path: Where ``canvas.manifest.json`` lands.
            Vue/Svelte use ``public/`` (served as a static asset);
            Flutter uses ``assets/``.
        shared_enums_dir: Directory under frontend root where per-enum
            files are emitted. The pipeline appends
            ``<enum_stem>.<ext>`` based on the emitter flavour.
        shared_enums_emitter: ``"typescript"`` or ``"dart"``. Chooses
            the emitter output + file extension.
    """

    framework: FrontendFramework
    ui_protocol_path: str
    ui_protocol_emitter: EmitterFlavour
    canvas_manifest_path: str
    shared_enums_dir: str
    shared_enums_emitter: EmitterFlavour


FRONTEND_LAYOUTS: dict[FrontendFramework, FrontendLayout] = {}


def register_frontend_layout(layout: FrontendLayout) -> None:
    """Register a :class:`FrontendLayout`. Raises on duplicate key.

    Plugins call this from their ``register(api)`` entry point after
    registering the corresponding ``FrontendFramework`` via
    :meth:`ForgeAPI.add_frontend`.
    """
    if layout.framework in FRONTEND_LAYOUTS:
        raise ValueError(f"FrontendLayout for {layout.framework.value!r} is already registered")
    FRONTEND_LAYOUTS[layout.framework] = layout


def get_frontend_layout(framework: FrontendFramework) -> FrontendLayout | None:
    """Return the layout for a framework, or ``None`` if unregistered."""
    return FRONTEND_LAYOUTS.get(framework)


# -----------------------------------------------------------------------------
# Built-in layouts — mirror the pre-Epic-O hardcoded paths byte-for-byte.
# -----------------------------------------------------------------------------


register_frontend_layout(
    FrontendLayout(
        framework=FrontendFramework.VUE,
        ui_protocol_path="src/features/ai_chat/ui_protocol.gen.ts",
        ui_protocol_emitter="typescript",
        canvas_manifest_path="public/canvas.manifest.json",
        shared_enums_dir="src/shared/enums",
        shared_enums_emitter="typescript",
    )
)

register_frontend_layout(
    FrontendLayout(
        framework=FrontendFramework.SVELTE,
        ui_protocol_path="src/lib/features/chat/ui_protocol.gen.ts",
        ui_protocol_emitter="typescript",
        canvas_manifest_path="public/canvas.manifest.json",
        shared_enums_dir="src/lib/shared/enums",
        shared_enums_emitter="typescript",
    )
)

register_frontend_layout(
    FrontendLayout(
        framework=FrontendFramework.FLUTTER,
        ui_protocol_path="lib/src/features/chat/domain/ui_protocol.gen.dart",
        ui_protocol_emitter="dart",
        canvas_manifest_path="assets/canvas.manifest.json",
        shared_enums_dir="lib/src/shared/enums",
        shared_enums_emitter="dart",
    )
)

"""Tests for Epic O's ``FrontendLayout`` registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.config import FrontendFramework
from forge.frontends import (
    FRONTEND_LAYOUTS,
    FrontendLayout,
    get_frontend_layout,
    register_frontend_layout,
)


def test_every_builtin_framework_has_a_layout() -> None:
    """Every FrontendFramework except NONE has a registered layout."""
    for framework in FrontendFramework:
        if framework is FrontendFramework.NONE:
            continue
        assert get_frontend_layout(framework) is not None, (
            f"{framework.value} is a built-in but has no FrontendLayout"
        )


def test_vue_layout_fields_match_pre_epic_o_paths() -> None:
    layout = get_frontend_layout(FrontendFramework.VUE)
    assert layout is not None
    assert layout.ui_protocol_path == "src/features/ai_chat/ui_protocol.gen.ts"
    assert layout.ui_protocol_emitter == "typescript"
    assert layout.canvas_manifest_path == "public/canvas.manifest.json"
    assert layout.shared_enums_dir == "src/shared/enums"
    assert layout.shared_enums_emitter == "typescript"


def test_svelte_layout_fields_match_pre_epic_o_paths() -> None:
    layout = get_frontend_layout(FrontendFramework.SVELTE)
    assert layout is not None
    assert layout.ui_protocol_path == "src/lib/features/chat/ui_protocol.gen.ts"
    assert layout.shared_enums_dir == "src/lib/shared/enums"


def test_flutter_layout_fields_match_pre_epic_o_paths() -> None:
    layout = get_frontend_layout(FrontendFramework.FLUTTER)
    assert layout is not None
    assert (
        layout.ui_protocol_path
        == "lib/src/features/chat/domain/ui_protocol.gen.dart"
    )
    assert layout.ui_protocol_emitter == "dart"
    assert layout.canvas_manifest_path == "assets/canvas.manifest.json"
    assert layout.shared_enums_emitter == "dart"


def test_register_rejects_duplicate_framework() -> None:
    existing = get_frontend_layout(FrontendFramework.VUE)
    assert existing is not None
    duplicate = FrontendLayout(
        framework=FrontendFramework.VUE,
        ui_protocol_path="something/else.ts",
        ui_protocol_emitter="typescript",
        canvas_manifest_path="other/canvas.manifest.json",
        shared_enums_dir="other/enums",
        shared_enums_emitter="typescript",
    )
    with pytest.raises(ValueError, match="already registered"):
        register_frontend_layout(duplicate)


def test_plugin_frontend_can_register_layout() -> None:
    """A plugin-added FrontendFramework value can ship its own layout.

    Uses patch.dict to give the test its own isolated registry so the
    side-effectful register_frontend_layout call doesn't leak.
    """
    # Simulate a plugin framework value — FrontendFramework is a
    # StrEnum with PLUGIN-added members, but we don't need to actually
    # register a new enum value for this test. Swap the registry for
    # an empty one so re-registration doesn't collide with built-ins.
    with patch.dict(FRONTEND_LAYOUTS, clear=True):
        plugin_layout = FrontendLayout(
            framework=FrontendFramework.VUE,  # stand-in for a plugin member
            ui_protocol_path="src/api/types.ts",
            ui_protocol_emitter="typescript",
            canvas_manifest_path="static/canvas.manifest.json",
            shared_enums_dir="src/shared",
            shared_enums_emitter="typescript",
        )
        register_frontend_layout(plugin_layout)
        assert get_frontend_layout(FrontendFramework.VUE) is plugin_layout

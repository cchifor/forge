"""Tests for the canvas error boundary (v2 Theme 8-C2).

Two regression guards:

* The Vue canvas package ships a ``CanvasError.vue`` component and
  re-exports it from its public entry. Without the export, the
  template author can't pull in the boundary even if they wanted to.
* The Vue frontend template wraps the canvas activity router in
  ``<CanvasError>``. Without that wrap, a crashing canvas component
  cascades up to ``CanvasPane`` and tears down the entire pane.

These tests are intentionally byte-level (string-presence) rather than
parsing the Vue SFC AST. The boundary contract here is "the literal
component name appears in the right files" — anything more elaborate
would itself need a hand-synced fixture.

Svelte/Dart counterparts are tracked for a follow-up PR.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_PKG_CANVAS_ERROR = _REPO_ROOT / "packages" / "canvas-vue" / "src" / "components" / "CanvasError.vue"
_PKG_INDEX = _REPO_ROOT / "packages" / "canvas-vue" / "src" / "index.ts"
_TEMPLATE_DIR = (
    _REPO_ROOT
    / "forge"
    / "templates"
    / "apps"
    / "vue-frontend-template"
    / "template"
    / "src"
    / "features"
    / "ai_chat"
    / "canvas"
)
_TEMPLATE_PANE = _TEMPLATE_DIR / "CanvasPane.vue"
_TEMPLATE_ERROR = _TEMPLATE_DIR / "CanvasError.vue"


def test_canvas_vue_package_ships_canvas_error_component() -> None:
    """The canvas-vue package contains a CanvasError.vue source file."""
    assert _PKG_CANVAS_ERROR.is_file(), f"missing {_PKG_CANVAS_ERROR}"
    source = _PKG_CANVAS_ERROR.read_text(encoding="utf-8")
    # onErrorCaptured is the load-bearing Vue 3 hook that makes this an
    # error boundary in the first place. If the file exists but doesn't
    # subscribe to that hook, the boundary is a no-op.
    assert "onErrorCaptured" in source, "CanvasError.vue must use onErrorCaptured"


def test_canvas_vue_package_exports_canvas_error() -> None:
    """The package entry re-exports CanvasError for template consumers."""
    source = _PKG_INDEX.read_text(encoding="utf-8")
    assert "CanvasError" in source, "CanvasError missing from packages/canvas-vue/src/index.ts"
    assert "CanvasError.vue" in source, (
        "CanvasError export in index.ts must point at the .vue file"
    )


def test_vue_template_canvas_pane_wraps_in_canvas_error() -> None:
    """The generated CanvasPane wraps canvas activities in <CanvasError>."""
    source = _TEMPLATE_PANE.read_text(encoding="utf-8")
    # Open tag and close tag — guards against importing-but-not-using.
    assert "<CanvasError" in source, "<CanvasError> not used in CanvasPane.vue"
    assert "</CanvasError>" in source, (
        "<CanvasError> opened but not closed in CanvasPane.vue"
    )
    # The boundary must wrap the engine router, not just sit alongside.
    # We can't AST-check, but we can assert relative ordering of markers.
    open_idx = source.index("<CanvasError")
    close_idx = source.index("</CanvasError>")
    assert "<AgUiEngine" in source[open_idx:close_idx], (
        "<AgUiEngine> must live inside the <CanvasError> boundary"
    )


def test_vue_template_ships_canvas_error_sibling() -> None:
    """The template ships a local CanvasError.vue so it has no new dep."""
    assert _TEMPLATE_ERROR.is_file(), f"missing {_TEMPLATE_ERROR}"
    source = _TEMPLATE_ERROR.read_text(encoding="utf-8")
    assert "onErrorCaptured" in source, (
        "template CanvasError.vue must use onErrorCaptured"
    )

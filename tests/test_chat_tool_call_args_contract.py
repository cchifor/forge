"""Cross-stack contract: TOOL_CALL_ARGS handling in the three frontend reducers.

Pillar G.2 (`/home/c4/.claude/plans/deep-gliding-mccarthy.md`) ships a
collapsible JSON preview of streamed tool-call arguments across the
Vue, Svelte, and Flutter chat reducers. The hard-cross-stack
requirement is that the **same client-side state shape**
(``argsBuffer`` + ``argsPretty``) and the **same JSON-parse-fallback
behaviour** ship in all three stacks so the contract test in
``tests/test_agent_event_contract.py`` doesn't go red the moment a
runtime drifts.

This file checks that:

1. Each ``ToolCallInfo`` model carries the two new client-side fields
   (``argsBuffer`` + ``argsPretty``).
2. Each reducer / agent client wires a TOOL_CALL_ARGS handler that
   appends ``event.delta`` to the buffer (not replaces).
3. Each reducer pretty-prints on END via the language-native
   2-space-indent JSON serializer (``JSON.stringify(..., null, 2)``
   for TS, ``JsonEncoder.withIndent('  ')`` for Dart).
4. Each reducer falls back to the raw buffer on JSON parse error so
   the UI always shows something for debugging.

Why static-string assertions? The actual reducer behavior is verified
by the per-stack unit tests (Vue + Svelte vitest, Flutter
flutter_test). This file's job is the meta-contract: a regression in
one stack — say Vue drops the JSON fallback and lets the exception
escape — should fail this test even though the per-stack vitest still
passes (because Vue's own test got "fixed" alongside the regression).

Cross-stack consistency for TOOL_CALL_ARGS was *the* original Pillar
G.2 motivation: pre-G.2 the Flutter reducer at
``agent_state_reducer.dart`` had a ``// Args streaming for live
tool-call display — not surfaced in v1`` TODO and Vue/Svelte silently
discarded the event. The contract test pins the fix so future
"refactors" can't silently un-ship the feature.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Per-stack file paths — the reducer + ``ToolCallInfo`` model location
# in each frontend template. Centralised here so a template move
# updates one constant rather than rippling across six asserts.
# ---------------------------------------------------------------------------

VUE_REDUCER = (
    _REPO_ROOT / "packages/canvas-core/src/reducer.ts"
)
VUE_TYPES = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src/features"
    / "ai_chat/types.ts"
)
VUE_UI = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src/features"
    / "ai_chat/ui/ToolCallStatus.vue"
)
VUE_TEST = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src/features"
    / "ai_chat/composables/useAgentClient.test.ts"
)

SVELTE_REDUCER = (
    _REPO_ROOT / "packages/canvas-core/src/reducer.ts"
)
SVELTE_TYPES = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src/lib"
    / "features/chat/chat.types.ts"
)
SVELTE_UI = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src/lib"
    / "features/chat/ui/ToolCallStatus.svelte"
)
SVELTE_TEST = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src/lib"
    / "features/chat/model/agent-client.test.ts"
)

FLUTTER_REDUCER = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib"
    / "src/features/chat/data/agent_state_reducer.dart"
)
FLUTTER_TYPES = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib"
    / "src/features/chat/domain/tool_call_info.dart"
)
FLUTTER_UI = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib"
    / "src/features/chat/presentation/widgets/tool_call_status.dart"
)
FLUTTER_TEST = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}/test"
    / "src/features/chat/data/agent_state_reducer_test.dart"
)


# ---------------------------------------------------------------------------
# Parametrize over the three stacks so a failure points at the
# specific stack (Vue/Svelte/Flutter) rather than a generic "one of
# the three is broken".
# ---------------------------------------------------------------------------

ALL_FILES: dict[str, tuple[Path, ...]] = {
    "vue": (VUE_REDUCER, VUE_TYPES, VUE_UI, VUE_TEST),
    "svelte": (SVELTE_REDUCER, SVELTE_TYPES, SVELTE_UI, SVELTE_TEST),
    "flutter": (FLUTTER_REDUCER, FLUTTER_TYPES, FLUTTER_UI, FLUTTER_TEST),
}


@pytest.mark.parametrize("stack,paths", list(ALL_FILES.items()))
def test_all_per_stack_files_exist(stack: str, paths: tuple[Path, ...]) -> None:
    """Every reducer + types + UI + test file ships in every stack."""
    missing = [p for p in paths if not p.exists()]
    assert not missing, f"{stack}: missing files {missing}"


# ---------------------------------------------------------------------------
# Field names — argsBuffer + argsPretty must show up in the
# ``ToolCallInfo`` model of each stack. Naming is load-bearing
# because the contract test in ``test_agent_event_contract.py``
# would otherwise miss a stack that quietly renamed the field.
# ---------------------------------------------------------------------------

TYPES_FILES: dict[str, Path] = {
    "vue": VUE_TYPES,
    "svelte": SVELTE_TYPES,
    "flutter": FLUTTER_TYPES,
}


@pytest.mark.parametrize("stack,path", list(TYPES_FILES.items()))
def test_tool_call_info_carries_argsbuffer(stack: str, path: Path) -> None:
    """``ToolCallInfo`` declares ``argsBuffer`` (client-side state)."""
    body = path.read_text(encoding="utf-8")
    assert "argsBuffer" in body, (
        f"{stack}: ToolCallInfo must declare argsBuffer "
        f"(client-side TOOL_CALL_ARGS accumulator)"
    )


@pytest.mark.parametrize("stack,path", list(TYPES_FILES.items()))
def test_tool_call_info_carries_argspretty(stack: str, path: Path) -> None:
    """``ToolCallInfo`` declares ``argsPretty`` (END-time pretty JSON)."""
    body = path.read_text(encoding="utf-8")
    assert "argsPretty" in body, (
        f"{stack}: ToolCallInfo must declare argsPretty "
        f"(client-side pretty-printed JSON set on TOOL_CALL_END)"
    )


# ---------------------------------------------------------------------------
# Reducer behaviour — each stack must:
#   1. Append (not replace) on TOOL_CALL_ARGS — guarded by the
#      ``argsBuffer ?? '' ) + delta`` pattern (TS) or
#      ``(tc.argsBuffer ?? '') + delta`` (Dart).
#   2. Pretty-print on TOOL_CALL_END — JSON.stringify(..., null, 2)
#      for TS, JsonEncoder.withIndent('  ') for Dart.
#   3. Catch the JSON parse error and fall back to the raw buffer.
# ---------------------------------------------------------------------------

REDUCER_FILES: dict[str, Path] = {
    "vue": VUE_REDUCER,
    "svelte": SVELTE_REDUCER,
    "flutter": FLUTTER_REDUCER,
}


@pytest.mark.parametrize("stack,path", list(REDUCER_FILES.items()))
def test_reducer_handles_tool_call_args(stack: str, path: Path) -> None:
    """Reducer references ``argsBuffer`` and a ``delta`` field.

    Static-string check — the actual append behaviour is verified by
    each stack's unit tests. This is the meta-guard against silently
    dropping the handler.
    """
    body = path.read_text(encoding="utf-8")
    assert "argsBuffer" in body, (
        f"{stack}: reducer must reference argsBuffer to accumulate TOOL_CALL_ARGS"
    )
    assert "delta" in body, (
        f"{stack}: reducer must read event.delta on TOOL_CALL_ARGS "
        f"(per AG-UI wire shape)"
    )


@pytest.mark.parametrize(
    "stack,path,marker",
    [
        # TS uses JSON.stringify with 2-space indent (third arg = 2).
        ("vue", VUE_REDUCER, "JSON.stringify(JSON.parse(buffer), null, 2)"),
        ("svelte", SVELTE_REDUCER, "JSON.stringify(JSON.parse(buffer), null, 2)"),
        # Dart uses JsonEncoder.withIndent('  ') from dart:convert.
        ("flutter", FLUTTER_REDUCER, "JsonEncoder.withIndent"),
    ],
)
def test_reducer_pretty_prints_on_end(stack: str, path: Path, marker: str) -> None:
    """``TOOL_CALL_END`` pretty-prints argsBuffer using a 2-space indent."""
    body = path.read_text(encoding="utf-8")
    assert marker in body, (
        f"{stack}: TOOL_CALL_END handler must pretty-print argsBuffer "
        f"via {marker!r}"
    )


@pytest.mark.parametrize("stack,path", list(REDUCER_FILES.items()))
def test_reducer_falls_back_on_parse_error(stack: str, path: Path) -> None:
    """JSON parse failure surfaces the raw buffer (not nothing, not an error)."""
    body = path.read_text(encoding="utf-8")
    # TS: ``try { ... } catch { pretty = buffer; }``
    # Dart: ``try { ... } catch (_) { return buffer; }``
    assert "catch" in body and "buffer" in body, (
        f"{stack}: TOOL_CALL_END handler must catch the JSON parse error "
        f"and fall back to the raw buffer so the user still sees something"
    )


# ---------------------------------------------------------------------------
# Collapsible UX — each stack's tool-call render must use a native
# collapsible primitive. We don't pin the exact widget across stacks
# (HTML <details> on web, ExpansionTile on Flutter is the right Material
# choice), just that *something* collapsible is in place.
# ---------------------------------------------------------------------------

UI_COLLAPSIBLE_MARKERS: dict[str, tuple[Path, tuple[str, ...]]] = {
    # HTML <details>/<summary> — works without JS state.
    "vue": (VUE_UI, ("<details", "<summary")),
    "svelte": (SVELTE_UI, ("<details", "<summary")),
    # Material-native collapsible — analogue of <details>.
    "flutter": (FLUTTER_UI, ("ExpansionTile",)),
}


@pytest.mark.parametrize("stack,spec", list(UI_COLLAPSIBLE_MARKERS.items()))
def test_ui_renders_collapsible_args(stack: str, spec: tuple[Path, tuple[str, ...]]) -> None:
    """UI uses a native collapsible primitive for the args preview."""
    path, markers = spec
    body = path.read_text(encoding="utf-8")
    for marker in markers:
        assert marker in body, (
            f"{stack}: tool-call UI must use {marker!r} to render the "
            f"collapsible args preview (Pillar G.2 collapsibility contract)"
        )

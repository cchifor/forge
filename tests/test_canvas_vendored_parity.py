"""Guard the canvas vendored copies — the source of truth users actually get.

Canvas-core was vendored into the generated frontend templates (commit
b6f7ffd); generated projects alias ``@forge/canvas-core`` to these vendored
copies (see ``vite.config.ts.jinja`` / ``svelte.config.js``), NOT to the
standalone ``packages/canvas-core``. Before this guard existed, the contract
test pointed at ``packages/canvas-core`` and so validated *dead code* while the
vendored reducer drifted (it had regressed to the camelCase ``toolCallId``
wire contract, vs the shipped snake_case ``tool_call_id`` fix — #214).

This test pins the canonical (vendored) copies directly:

* the Vue and Svelte vendored ``canvas-core`` trees stay byte-identical,
* the user-prompt path reads/emits snake_case ``tool_call_id`` (the
  ui-protocol schema), and
* the ``TOOL_CALL_*`` streaming path stays camelCase ``toolCallId`` (the
  pydantic-ai wire) — guarding against an over-correction that would break
  streaming.

Pure-Python static assertions: no Node/Dart toolchain required, so it runs in
the normal pytest lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

_VUE_DIR = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src/features"
    / "ai_chat/canvas-core"
)
_SVELTE_DIR = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src/lib"
    / "features/chat/canvas-core"
)
_FLUTTER_EVENT = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib"
    / "src/features/chat/data/ag_ui_event.dart"
)

# Every file in the vendored canvas-core tree. Vue and Svelte ship the SAME
# TypeScript source (only their host frontends differ), so these must stay
# byte-identical — divergence is the split-brain this test exists to catch.
_SHARED = (
    "ag_ui_client.ts",
    "events.ts",
    "index.ts",
    "mcp_approval_client.ts",
    "mcp_bridge.ts",
    "reducer.ts",
    "snapshot.ts",
)


@pytest.mark.parametrize("name", _SHARED)
def test_vue_svelte_vendored_byte_identical(name: str) -> None:
    vue = _VUE_DIR / name
    svelte = _SVELTE_DIR / name
    assert vue.is_file(), f"missing vendored Vue canvas-core file: {vue}"
    assert svelte.is_file(), f"missing vendored Svelte canvas-core file: {svelte}"
    assert vue.read_text(encoding="utf-8") == svelte.read_text(encoding="utf-8"), (
        f"vendored canvas-core/{name} drifted between Vue and Svelte"
    )


@pytest.mark.parametrize("reducer", [_VUE_DIR / "reducer.ts", _SVELTE_DIR / "reducer.ts"])
def test_user_prompt_reads_snake_case_primary(reducer: Path) -> None:
    """The user-prompt path uses snake_case ``tool_call_id`` (ui-protocol
    schema) as the primary key and snake_case output — the shipped 5b27264 fix.
    A regression to camelCase-only fails here."""
    body = reducer.read_text(encoding="utf-8")
    assert "v['tool_call_id'] ?? v['toolCallId']" in body, "snake-primary input key regressed"
    assert "return { tool_call_id:" in body, "snake-case output key regressed"
    assert "pendingPrompt.tool_call_id" in body, "clearPendingPromptIfMatches lookup regressed"


@pytest.mark.parametrize("events", [_VUE_DIR / "events.ts", _SVELTE_DIR / "events.ts"])
def test_tool_call_events_stay_camelcase(events: Path) -> None:
    """``TOOL_CALL_*`` streaming frames stay camelCase ``toolCallId`` — that's
    the pydantic-ai wire. Guards against over-correcting the whole file to
    snake_case and breaking streaming."""
    body = events.read_text(encoding="utf-8")
    assert body.count("frame['toolCallId']") >= 3, "TOOL_CALL_* must read camelCase toolCallId"


def test_flutter_tool_call_events_stay_camelcase() -> None:
    """Flutter's AG-UI event parse mirrors the wire: ``TOOL_CALL_*`` reads
    camelCase ``toolCallId`` (matching the TS vendored copies)."""
    assert _FLUTTER_EVENT.is_file(), f"missing flutter ag_ui_event.dart: {_FLUTTER_EVENT}"
    body = _FLUTTER_EVENT.read_text(encoding="utf-8")
    assert body.count("json['toolCallId']") >= 3, (
        "Flutter TOOL_CALL_* must read camelCase toolCallId"
    )

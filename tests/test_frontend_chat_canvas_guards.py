"""Regression: frontend chat/canvas resilience (audit #7, #25, #27).

Static guards over the Svelte + Flutter templates. Svelte behaviour is also
covered by a shipped vitest (agent-client.test.ts) that runs in generated
projects; Flutter has no runtime in this environment, so these grep guards are
the forge-CI gate for the Flutter side.
"""

from __future__ import annotations

from pathlib import Path

_APPS = Path(__file__).resolve().parent.parent / "forge/templates/apps"
_SVELTE = _APPS / "svelte-frontend-template/template/src/lib/features/chat"
_FLUTTER = _APPS / "flutter-frontend-template/{{project_slug}}/lib/src/features/chat"


def test_svelte_chat_client_has_stale_run_guard() -> None:
    src = (_SVELTE / "model/agent-client.svelte.ts").read_text(encoding="utf-8")
    assert "runGeneration" in src and "isCurrent" in src, (
        "svelte chat client must guard stale runs so resetThread mid-stream "
        "doesn't repopulate the cleared thread (#7)"
    )


def test_flutter_chat_notifier_has_stale_run_guard() -> None:
    src = (_FLUTTER / "presentation/chat_providers.dart").read_text(encoding="utf-8")
    assert "_runGeneration" in src and "myGeneration != _runGeneration" in src, (
        "flutter ChatNotifier must guard stale runs (#7)"
    )


def test_svelte_datatable_null_safe_and_boundary() -> None:
    dt = (_SVELTE / "canvas/DataTable.svelte").read_text(encoding="utf-8")
    pane = (_SVELTE / "canvas/CanvasPane.svelte").read_text(encoding="utf-8")
    # #25: null/heterogeneous rows must not throw; canvas pane has a boundary.
    assert "row?.[col.key]" in dt and "typeof r === 'object'" in dt
    assert "svelte:boundary" in pane


def test_flutter_datatable_guards_empty_columns() -> None:
    dt = (_FLUTTER / "canvas/activities/data_table.dart").read_text(encoding="utf-8")
    # #27: rows present but no columns must not trip Material's assert.
    assert "cols.isEmpty" in dt

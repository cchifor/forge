"""WS-5.3: generated chat clients must compile.

Two long-standing bugs made ``regenerate()`` a TypeScript compile error in
the generated Vue + Svelte chat templates:

* Vue ``useAgentClient.ts`` assigned to ``messages.value`` — but ``messages``
  is a read-only ``computed``. Assigning to it is a tsc error; the fix mutates
  the source ``snapshot`` (mirroring ``editAndResend``).
* Svelte ``agent-client.svelte.ts`` referenced ``isRunning`` / ``messages`` /
  ``lastError`` in ``regenerate()`` that were never declared in that scope.

These run in generated projects (no TS toolchain in the forge venv), so we
assert on the template source.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_VUE = (
    _ROOT
    / "forge/templates/apps/vue-frontend-template/template"
    / "src/features/ai_chat/composables/useAgentClient.ts"
)
_SVELTE = (
    _ROOT
    / "forge/templates/apps/svelte-frontend-template/template"
    / "src/lib/features/chat/model/agent-client.svelte.ts"
)


def test_vue_regenerate_does_not_assign_to_readonly_computed() -> None:
    src = _VUE.read_text(encoding="utf-8")
    # ``messages`` is a computed() — assigning to ``messages.value`` is a
    # read-only TS error. The fix must not do it.
    assert "messages.value = " not in src, (
        "useAgentClient.ts must not assign to the read-only computed "
        "`messages.value`; mutate snapshot.value.messages instead"
    )


def test_vue_regenerate_truncates_via_snapshot() -> None:
    src = _VUE.read_text(encoding="utf-8")
    # The regenerate path must truncate the real source-of-truth snapshot.
    assert "snapshot.value" in src and "regenerate" in src
    block = src.split("function regenerate", 1)[1].split("function ", 1)[0]
    assert "snapshot.value" in block, (
        "regenerate() must mutate snapshot.value (the source of truth), "
        "not the derived computed"
    )


def test_svelte_regenerate_uses_snapshot_fields_not_free_vars() -> None:
    src = _SVELTE.read_text(encoding="utf-8")
    block = src.split("function regenerate", 1)[1].split("\nfunction ", 1)[0]
    # The old code referenced undeclared `messages` / `isRunning` / `lastError`.
    assert "snapshot.messages" in block, "regenerate() must read snapshot.messages"
    assert "snapshot.isRunning" in block, "regenerate() must guard on snapshot.isRunning"
    assert "lastError" not in block, "regenerate() must not reference undeclared lastError"
    # No bare assignment to a `messages` free variable.
    assert "\tmessages = " not in block and " messages = " not in block, (
        "regenerate() must not assign to a free `messages` variable"
    )

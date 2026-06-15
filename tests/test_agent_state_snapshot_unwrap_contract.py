"""Cross-stack contract: ``deepagent.state_snapshot`` payload unwrap.

The deepagent backend emits the ``deepagent.state_snapshot`` CUSTOM
event with a **wrapped** payload: the agent state (cost/todos/files/…)
lives under ``value.state``, not at the root of ``value``:

    { "name": "deepagent.state_snapshot",
      "value": { "state": { "cost": ..., "todos": [...], ... } } }

Every frontend reducer must therefore unwrap ``value.state`` (falling
back to ``value`` for older/flat producers) before feeding it into the
agent-state model. If a reducer feeds the *raw, un-unwrapped* ``value``
into the model, the agent state never renders, and worse, later
``STATE_DELTA`` JSON-Patch ops target the wrong root (``/state/...``
instead of ``/...``).

Vue + Svelte unwrap via ``(value as Record<string, unknown>)['state']
?? value``. The Flutter reducer historically passed ``value`` straight
into ``AgentState.fromMap`` and ``rawAgentMap``, dropping the unwrap.

Why a static-string contract? The per-stack runtime behaviour is
verified by each stack's own unit tests (vitest / flutter_test). This
meta-contract guards against one stack silently dropping the unwrap
during a refactor — the per-stack test could get "fixed" alongside the
regression, but this cross-stack pin would still go red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Per-stack reducer file paths. Centralised so a template move updates
# one constant rather than rippling across asserts.
# ---------------------------------------------------------------------------

VUE_REDUCER = (
    _REPO_ROOT
    / "forge/templates/apps/vue-frontend-template/template/src/features"
    / "ai_chat/canvas-core/reducer.ts"
)

SVELTE_REDUCER = (
    _REPO_ROOT
    / "forge/templates/apps/svelte-frontend-template/template/src/lib"
    / "features/chat/canvas-core/reducer.ts"
)

FLUTTER_REDUCER = (
    _REPO_ROOT
    / "forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib"
    / "src/features/chat/data/agent_state_reducer.dart"
)

REDUCER_FILES: dict[str, Path] = {
    "vue": VUE_REDUCER,
    "svelte": SVELTE_REDUCER,
    "flutter": FLUTTER_REDUCER,
}


@pytest.mark.parametrize("stack,path", list(REDUCER_FILES.items()))
def test_reducer_file_exists(stack: str, path: Path) -> None:
    """Every stack ships a chat reducer."""
    assert path.exists(), f"{stack}: missing reducer at {path}"


@pytest.mark.parametrize("stack,path", list(REDUCER_FILES.items()))
def test_state_snapshot_branch_unwraps_value_state(stack: str, path: Path) -> None:
    """The ``deepagent.state_snapshot`` branch unwraps ``value.state``.

    The wire payload nests the agent state under ``value.state``;
    feeding the raw ``value`` in leaves the model empty and mis-roots
    later STATE_DELTA JSON-Patch ops. Each reducer must reference the
    ``state`` key inside the snapshot branch — ``['state']`` (TS *and*
    Dart map indexing) — to perform the unwrap.
    """
    body = path.read_text(encoding="utf-8")

    marker = "deepagent.state_snapshot"
    assert marker in body, f"{stack}: reducer has no {marker!r} branch"

    # Isolate the snapshot branch: from the branch marker up to the
    # next CUSTOM name (``deepagent.user_prompt``) so the assertion
    # can't be satisfied by an unwrap that lives in some other branch.
    start = body.index(marker)
    next_branch = body.find("deepagent.user_prompt", start)
    branch = body[start:next_branch] if next_branch != -1 else body[start:]

    assert "['state']" in branch, (
        f"{stack}: the {marker!r} branch must unwrap the nested "
        f"agent state via value['state'] (?? value) before feeding it "
        f"into the agent-state model. Without the unwrap the state "
        f"never renders and STATE_DELTA ops target the wrong root."
    )

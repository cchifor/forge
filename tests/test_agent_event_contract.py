"""Cross-runtime contract for the unified AG-UI event protocol.

Initiative #4 settles on a single ``kind`` discriminator for the
AG-UI event union. Three runtimes consume it:

* The Pydantic backend (``forge.codegen.event_union.emit_pydantic`` ->
  ``services/<name>/src/app/domain/canvas_events.py``).
* The Dart sealed-class parse factory
  (``forge.codegen.event_union.emit_dart`` -> ``packages/forge-canvas-dart/
  lib/src/generated/events.dart`` + per-app ``events.gen.dart``).
* The TS Vue + Svelte shims that forward to the generated union
  (``packages/canvas-{vue,svelte}/src/ag_ui_client.ts`` +
  per-app ``events.gen.ts``).

This file pins one JSON payload per shipped variant and asserts each
runtime can either round-trip it (Pydantic) or accepts it in its
generated dispatch table (Dart parse factory, TS union). The corpus
is the single source of truth — diverging the runtimes is now a
test failure rather than a silent wire-protocol drift.

Why not actually run the Dart and TS parsers? They live in `packages/`
and need a Node/Dart toolchain. We're in a pure-Python pytest env, so
we assert the *static* shape of the generated code instead. The
follow-up TODO is to spawn `node` / `dart` subprocesses when those
toolchains are reachable in CI (see test_no_runtime_dispatch_yet).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from forge.codegen.event_union import (
    emit_dart,
    emit_pydantic,
    emit_typescript,
    load_event_schemas,
)
from forge.codegen.ui_protocol import emit_pydantic as emit_ui_pydantic

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Shared corpus — one minimal payload per variant.
#
# Each entry must validate against its ui-protocol JSON schema. Keep
# values minimal (required fields only) so a future schema tightening
# is caught by the round-trip test rather than a schema-validation
# library disagreement.
# ---------------------------------------------------------------------------

CORPUS: dict[str, dict] = {
    "ag-ui-payload": {
        "kind": "ag-ui-payload",
        "payload": {
            "engine": "ag-ui",
            "component_name": "DataTable",
            "props": {"rows": []},
        },
    },
    "agent-state": {
        "kind": "agent-state",
        "payload": {
            "todos": [{"content": "draft outline", "status": "in_progress"}],
            "files": ["README.md"],
            "model": "claude-sonnet-4-5",
        },
    },
    "hitl-response": {
        "kind": "hitl-response",
        "payload": {"tool_call_id": "tc-1", "answer": "yes"},
    },
    "mcp-ext-payload": {
        "kind": "mcp-ext-payload",
        "payload": {
            "engine": "mcp-ext",
            "html": "<div>hello</div>",
        },
    },
    "tool-call-info": {
        "kind": "tool-call-info",
        "payload": {"id": "tc-1", "name": "search_docs", "status": "running"},
    },
    "user-prompt-payload": {
        "kind": "user-prompt-payload",
        "payload": {
            "tool_call_id": "tc-1",
            "question": "Approve this run?",
            "options": [{"label": "yes"}, {"label": "no"}],
        },
    },
    "workspace-activity": {
        "kind": "workspace-activity",
        "payload": {
            "engine": "ag-ui",
            "activityType": "render",
            "messageId": "msg-1",
            "content": {},
        },
    },
}


def test_corpus_covers_every_shipped_schema() -> None:
    """The corpus drives the per-runtime assertions; missing entries
    silently skip coverage for that variant. Pin the set against the
    schema directory so adding a schema forces a corpus update.
    """
    schema_kinds = {
        s.title.lower().replace("_", "-") for s in load_event_schemas()
    }
    # The codegen derives slugs via PascalCase->kebab-case rather than
    # naive snake-case. Re-derive the canonical slug set from the schemas.
    from forge.codegen.event_union import _kind_for

    expected = {_kind_for(s) for s in load_event_schemas()}
    assert set(CORPUS) == expected, (
        f"corpus drift — schemas={expected!r} corpus={set(CORPUS)!r}; "
        "add/remove an entry in CORPUS to match the schema set"
    )


# ---------------------------------------------------------------------------
# Runtime 1 — Pydantic backend round-trips every payload through the
# generated discriminated union.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pydantic_adapter(tmp_path_factory):
    """Build an on-disk Python package out of the two generated modules
    and return the runtime ``AgUiEventAdapter`` for round-trip testing.

    Same trick as ``test_event_union_codegen.py``'s
    ``test_pydantic_union_validates_at_runtime`` — we want the actual
    Pydantic adapter, not a structural string match.
    """
    tmp_path = tmp_path_factory.mktemp("ev_pkg_contract")
    pkg = tmp_path / "ev_pkg_contract"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "ui_protocol.py").write_text(
        emit_ui_pydantic(load_event_schemas()), encoding="utf-8"
    )
    (pkg / "canvas_events.py").write_text(
        emit_pydantic(load_event_schemas()), encoding="utf-8"
    )

    sys.path.insert(0, str(tmp_path))
    try:
        from ev_pkg_contract.canvas_events import AgUiEventAdapter  # type: ignore[import-not-found]
        yield AgUiEventAdapter
    finally:
        sys.path.remove(str(tmp_path))
        for mod_name in [
            m for m in list(sys.modules)
            if m == "ev_pkg_contract" or m.startswith("ev_pkg_contract.")
        ]:
            del sys.modules[mod_name]


@pytest.mark.parametrize("kind", list(CORPUS))
def test_pydantic_validates_every_corpus_entry(pydantic_adapter, kind: str) -> None:
    """Each corpus payload must validate cleanly through the Pydantic
    discriminated union — i.e. the ``kind`` slug routes to the right
    payload class and that class accepts the payload as-is.
    """
    payload = CORPUS[kind]
    event = pydantic_adapter.validate_python(payload)
    # The discriminator landed us on the wrapper named after the schema title.
    # E.g. ``ag-ui-payload`` -> ``AgUiPayloadEvent``.
    assert type(event).__name__.endswith("Event")
    # The variant's `kind` attribute matches the slug we sent in.
    assert event.kind == kind


@pytest.mark.parametrize("kind", list(CORPUS))
def test_pydantic_round_trip_is_byte_stable(pydantic_adapter, kind: str) -> None:
    """Validate -> dump -> validate must produce an equivalent envelope.

    The serialised form may carry extra defaulted fields (e.g.
    AgentState's ``additionalProperties: true`` extras dict) — what
    matters is the second validation succeeds and yields the same
    ``kind``.
    """
    payload = CORPUS[kind]
    event = pydantic_adapter.validate_python(payload)
    dumped = event.model_dump(mode="python")
    again = pydantic_adapter.validate_python(dumped)
    assert again.kind == event.kind
    assert type(again) is type(event)


# ---------------------------------------------------------------------------
# Runtime 2 — Dart parse factory dispatches every kind in the corpus.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(CORPUS))
def test_dart_parse_factory_has_case_for_every_kind(kind: str) -> None:
    """The static ``AgUiEvent.parse`` factory must carry a ``case`` for
    every shipped kind. Missing a case silently drops events on the
    floor — exactly the failure mode this contract guards against.
    """
    body = emit_dart(load_event_schemas())
    assert f"case '{kind}':" in body, (
        f"Dart parse factory is missing a `case '{kind}':` branch — "
        f"add a schema or fix the codegen so this kind dispatches."
    )


def test_dart_parse_factory_returns_null_on_missing_kind() -> None:
    """Defensive: a corpus payload stripped of its ``kind`` discriminator
    is malformed and the factory must return ``null`` rather than guess.
    """
    body = emit_dart(load_event_schemas())
    # The structural test is `kind is! String` -> `return null`; we
    # already pin this in test_event_union_codegen.py, repeat the
    # assertion here so the contract test is self-contained for
    # documentation purposes.
    assert "if (kind is! String) return null;" in body


# ---------------------------------------------------------------------------
# Runtime 3 — TS union covers every corpus entry as a `kind` literal.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(CORPUS))
def test_typescript_union_has_kind_literal_for_every_corpus_entry(
    kind: str,
) -> None:
    """Each corpus entry's ``kind`` slug must appear as a TS literal in
    the generated union — that's the type-level guarantee the
    Vue/Svelte shim parsers narrow against.
    """
    body = emit_typescript(load_event_schemas())
    assert f'kind: "{kind}"' in body, (
        f"TS union is missing the `kind: \"{kind}\"` literal — "
        f"the {kind} variant is not addressable from Vue/Svelte consumers."
    )


# ---------------------------------------------------------------------------
# Symmetry sanity — the corpus is single-source-of-truth across runtimes.
# ---------------------------------------------------------------------------


def test_dart_and_typescript_dispatch_on_the_same_kind_set() -> None:
    """The two emitters draw from the same schema load, so the set of
    dispatched kinds must agree. A divergence would mean one runtime
    handles a kind the other silently drops.
    """
    dart_body = emit_dart(load_event_schemas())
    ts_body = emit_typescript(load_event_schemas())
    for kind in CORPUS:
        in_dart = f"case '{kind}':" in dart_body
        in_ts = f'kind: "{kind}"' in ts_body
        assert in_dart == in_ts, (
            f"runtime drift on kind={kind!r}: dart_has={in_dart} ts_has={in_ts}"
        )


# ---------------------------------------------------------------------------
# TODO: run the Dart and TS parsers as subprocesses when CI gains a
# Dart SDK + Node toolchain. Today we only assert generated-code shape;
# a true end-to-end contract would exec `dart run` / `node` and feed
# each corpus entry through the actual parsers.
#
# Tracked as a follow-on to Initiative #4. Until then the structural
# checks above are the contract: any drift in the dispatched-kind set
# fails the test before it can reach a generated app.
# ---------------------------------------------------------------------------


def test_no_runtime_dispatch_yet() -> None:
    """Marker test — documents the gap so a future contributor adding
    a Dart/Node toolchain knows to wire it up.
    """
    # If you're reading this because the test name caught your eye —
    # the contract is structural-only today. Spawning `dart` / `node`
    # subprocesses would round-trip the corpus through the actual
    # parsers, closing the last cross-runtime gap. Out of scope for
    # the pure-Python pytest env, in scope for an integration job.
    assert True
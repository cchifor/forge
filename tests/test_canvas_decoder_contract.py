"""Canvas-decoder cross-runtime contract (Initiative #9).

The AG-UI event protocol is implemented three times — once on the
Python backend (Pydantic discriminated union, emitted by
:mod:`forge.codegen.event_union`) and twice on the canvas frontends
(Dart sealed-class ``AgUiEvent.parse`` factory in
``packages/forge-canvas-dart/lib/src/generated/events.dart``; TypeScript
union + ``getEventKind`` helper in
``packages/canvas-vue/src/generated/events.ts`` and the byte-identical
``packages/canvas-svelte/src/generated/events.ts``). All three are
generated from the same JSON schemas under
``forge/templates/_shared/ui-protocol/`` — so the codegen invariant
is structural (covered by :mod:`tests.test_event_union_codegen`),
but the *runtime* contract — that a Pydantic-serialised frame round-
trips byte-identically through the Dart parser, and vice versa — is
what this file pins.

Why "byte-identical" matters: production agent traffic flows
Pydantic → wire → Dart (Flutter chat client). A drift in even one
field name or null-handling rule means events of that variant get
silently dropped or mis-parsed at the client. The
:class:`tests.test_event_union_codegen.TestEmitDart.test_parse_factory_dispatches_every_kind`
structural test catches "wrong case branch" drift; this file catches
"right case branch, but the payload field shape disagrees" drift —
e.g. a Pydantic field named ``tool_call_id`` paired with a Dart
field named ``toolCallId`` would round-trip on its own side but
collapse on the cross-runtime contract.

Coverage matrix
---------------
+----------------+--------+--------+-----------------------+
| Variant        | Python | Dart   | TypeScript (Vue+Svelte)|
+================+========+========+=======================+
| ag-ui-payload  | always | if Dart| if Node               |
| agent-state    | always | if Dart| if Node               |
| hitl-response  | always | if Dart| if Node               |
| mcp-ext-payload| always | if Dart| if Node               |
| tool-call-info | always | if Dart| if Node               |
| user-prompt-…  | always | if Dart| if Node               |
| workspace-…    | always | if Dart| if Node               |
+----------------+--------+--------+-----------------------+

The Pydantic path runs on every CI host (Python is unconditional).
The Dart path runs when ``dart`` is on PATH — the test SKIPs with an
explicit message when it isn't, so CI without Flutter doesn't
masquerade as covering this contract. Same for the TypeScript path
(``node`` on PATH).

Field-set discipline: corpus envelopes set EVERY declared field
(including optionals). Both runtimes serialise unset-with-default
fields as JSON ``null`` rather than omitting the key, so leaving an
optional unset would surface as a spurious envelope diff rather than
a real contract failure.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from forge.codegen.event_union import emit_pydantic, load_event_schemas
from forge.codegen.ui_protocol import emit_pydantic as emit_ui_pydantic

# Shared corpus — ONE envelope per AG-UI event variant. The shape is
# the same wire format the backend Pydantic union emits and the Dart
# parser consumes: ``{"kind": "<slug>", "payload": {...}}``.
#
# Every declared schema field is set (no implicit defaults / Nones)
# because:
#   - Pydantic ``model_dump()`` emits unset optionals as ``null``.
#   - Dart ``toJson()`` includes every declared field — null when
#     the source field is null.
# Leaving an optional implicit would surface as ``{"foo": null}`` on
# both sides, which is fine, but pinning it explicitly keeps the
# corpus self-documenting and makes accidental schema-field drift
# (an emitter dropping a field on one side) crash the
# byte-equality assertion with a useful diff rather than a flapping
# "left has null, right omitted" message.
#
# ``additionalProperties: true`` fields (currently AgentState only)
# carry NO extras in this corpus — Dart's generated ``toJson`` does
# not round-trip extras (the ``extras`` field exists but is not
# emitted), and the canvas-decoder contract is about the declared
# schema, not the catch-all extension surface. A separate test would
# pin the extras behaviour if/when the Dart codegen learns to
# round-trip them.
CORPUS: dict[str, dict[str, object]] = {
    "ag-ui-payload": {
        "kind": "ag-ui-payload",
        "payload": {
            "engine": "ag-ui",
            "component_name": "DataTable",
            "props": {"columns": ["id", "name"], "rows": []},
        },
    },
    "agent-state": {
        "kind": "agent-state",
        "payload": {
            "todos": [{"content": "wire decoder", "status": "in_progress"}],
            "files": ["a.py", "b.py"],
            "uploads": [{"name": "diag.png", "path": "/tmp/diag.png", "size": 12345}],
            "cost": {
                "total_usd": 0.5,
                "total_tokens": 1024,
                "run_usd": 0.1,
                "run_tokens": 256,
            },
            "context": {
                "usage_pct": 0.42,
                "current_tokens": 8000,
                "max_tokens": 200000,
            },
            "model": "claude-sonnet-4",
        },
    },
    "hitl-response": {
        "kind": "hitl-response",
        "payload": {"tool_call_id": "call_abc", "answer": "approve"},
    },
    "mcp-ext-payload": {
        "kind": "mcp-ext-payload",
        "payload": {
            "engine": "mcp-ext",
            "html": "<div>hello</div>",
            "initialContext": {"theme": "dark", "userId": "u_1"},
        },
    },
    "tool-call-info": {
        "kind": "tool-call-info",
        "payload": {
            "id": "tc_1",
            "name": "list_items",
            "status": "running",
            "args": {"limit": 10},
        },
    },
    "user-prompt-payload": {
        "kind": "user-prompt-payload",
        "payload": {
            "tool_call_id": "call_xyz",
            "question": "Continue?",
            "options": [
                {"label": "Yes", "description": "Proceed", "recommended": "true"},
                {"label": "No", "description": "Stop", "recommended": "false"},
            ],
        },
    },
    "workspace-activity": {
        "kind": "workspace-activity",
        "payload": {
            "engine": "ag-ui",
            "activityType": "render",
            "messageId": "msg_1",
            "content": {"foo": "bar"},
        },
    },
}


# ----------------------------------------------------------------------
# Pydantic fixtures
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def pydantic_adapter():
    """Build the generated ``AgUiEventAdapter`` on a tempdir package.

    Mirrors the on-disk shape forge ships into each generated Python
    service: ``ui_protocol.py`` (1B emitter) + ``canvas_events.py``
    (2B emitter) under a Python package. The adapter is the
    ``TypeAdapter[AgUiEvent]`` used by the backend's ``/ws/agent``
    handler to validate frames before they hit the application code.

    The package is left on disk for the duration of the module (a
    pytest ``module``-scope fixture) so every variant test reuses the
    same import — re-importing fresh per test would multiply this
    module's runtime by ~7x without strengthening the contract.
    """
    pkg_root = Path(tempfile.mkdtemp(prefix="canvas-contract-pkg-"))
    pkg = pkg_root / "canvas_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    schemas = load_event_schemas()
    (pkg / "ui_protocol.py").write_text(emit_ui_pydantic(schemas), encoding="utf-8")
    (pkg / "canvas_events.py").write_text(emit_pydantic(schemas), encoding="utf-8")

    sys.path.insert(0, str(pkg_root))
    try:
        # Re-import each time the test runs in case sys.modules has a
        # stale reference from another test's tempdir.
        for mod_name in [
            m for m in list(sys.modules) if m == "canvas_pkg" or m.startswith("canvas_pkg.")
        ]:
            del sys.modules[mod_name]
        # ``canvas_pkg`` is created at runtime by the fixture above
        # (writing the emitted modules into a tempdir on sys.path); ty
        # has no way to see it statically. Driven via
        # ``importlib.import_module`` so the import path is computed
        # at runtime and ty doesn't try (and fail) to resolve it at
        # type-check time.
        import importlib  # noqa: PLC0415

        AgUiEventAdapter = importlib.import_module(
            "canvas_pkg.canvas_events"
        ).AgUiEventAdapter
        yield AgUiEventAdapter
    finally:
        sys.path.remove(str(pkg_root))
        for mod_name in [
            m for m in list(sys.modules) if m == "canvas_pkg" or m.startswith("canvas_pkg.")
        ]:
            del sys.modules[mod_name]
        shutil.rmtree(pkg_root, ignore_errors=True)


def _canonical(envelope: dict[str, object]) -> str:
    """Sort-keys JSON serialise the envelope for byte-equality compare.

    Both Pydantic and Dart can return keys in declaration order; the
    raw bytes may legitimately differ even when the logical payload
    matches. Canonicalising via ``sort_keys=True`` neutralises that
    so a difference in the produced string is a REAL contract
    violation, not a cosmetic ordering blip.
    """
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"))


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


class TestCorpusCovers:
    """The corpus must cover every shipped variant, no more and no less.

    A drift between corpus and schema set is itself a contract
    violation — if a new variant lands without a corpus entry, the
    cross-runtime contract was never checked for it; if a corpus
    entry no longer maps to a shipped variant, the test is
    silently testing nothing.
    """

    def test_corpus_keys_match_loaded_schemas(self) -> None:
        from forge.codegen.event_union import _kind_for

        kinds = {_kind_for(s) for s in load_event_schemas()}
        assert set(CORPUS) == kinds, (
            f"corpus drifted from schema set; missing="
            f"{kinds - set(CORPUS)}, extra={set(CORPUS) - kinds}"
        )


class TestExtrasGapIsAcknowledged:
    """Pin the known ``additionalProperties: true`` gap so a fix gets
    noticed.

    The AG-UI ``AgentState`` schema allows ``additionalProperties:
    true`` (callers can attach arbitrary state). Pydantic with
    ``ConfigDict(extra="allow")`` round-trips extras correctly; the
    generated Dart class has an ``extras`` field but ``fromJson``
    doesn't fill it and ``toJson`` doesn't emit it (see
    ``packages/forge-canvas-dart/lib/src/generated/events.dart`` —
    ``class AgentState``). The CORPUS deliberately omits extras so
    the cross-runtime byte-equality contract test isn't asserting an
    asymmetry that lives in Init #8's codegen surface.

    This pin documents the gap in code so a future Dart codegen fix
    (the right place: ``forge/codegen/event_union.py:emit_dart``)
    causes this test to fail with a "remove the gap pin" message,
    forcing the contract corpus to grow an extras case at the same
    time.
    """

    def test_dart_agent_state_tojson_does_not_emit_extras(self) -> None:
        """The shipped Dart ``AgentState.toJson`` must NOT yet round-
        trip extras. Codex review flagged the asymmetry; we acknowledge
        it as a known gap rather than silently mask it. Init #8 owns
        the canvas-decoder codegen and would fix this in
        ``emit_dart``.
        """
        dart_src = (
            Path(__file__).resolve().parent.parent
            / "packages"
            / "forge-canvas-dart"
            / "lib"
            / "src"
            / "generated"
            / "events.dart"
        ).read_text(encoding="utf-8")
        # Pinned by source-level inspection: the AgentState toJson
        # block must contain the declared fields and NOT include
        # ``extras``. The day Init #8 lands a fix, the assertion
        # below flips and this test fails with "extras now round-
        # trips — extend CORPUS to cover the case and delete this
        # pin".
        assert "'todos': todos" in dart_src, "AgentState.toJson surface drifted"
        assert "'extras'" not in dart_src, (
            "AgentState.toJson now emits 'extras' — the Init #8 codegen "
            "fix landed. Extend tests/test_canvas_decoder_contract.py "
            "CORPUS['agent-state'] to include extras and delete this "
            "guard."
        )


class TestPydanticRoundTrip:
    """Every corpus envelope must round-trip through the Pydantic
    discriminated-union adapter byte-identically. This is the contract
    surface the Python backend ships — a regression here would mean a
    generated service couldn't reproduce its own input frames.
    """

    @pytest.mark.parametrize("kind", sorted(CORPUS))
    def test_pydantic_roundtrip_is_byte_identical(self, pydantic_adapter, kind: str):
        envelope = CORPUS[kind]
        parsed = pydantic_adapter.validate_python(envelope)
        # ``mode='json'`` matches the on-the-wire shape (e.g. UUIDs
        # would serialise to strings, floats stay as numbers) — the
        # exact format the Dart/TS side will receive.
        dumped = parsed.model_dump(mode="json")
        assert _canonical(dumped) == _canonical(envelope), (
            f"Pydantic round-trip for {kind!r} produced a non-identical envelope.\n"
            f"  expected: {_canonical(envelope)}\n"
            f"  actual:   {_canonical(dumped)}"
        )


# ----------------------------------------------------------------------
# Dart runtime contract
# ----------------------------------------------------------------------


def _have_dart() -> bool:
    return shutil.which("dart") is not None


_DART_HARNESS = r"""
// Auto-generated by tests/test_canvas_decoder_contract.py.
// Reads a JSON corpus map from stdin, parses each envelope via
// `AgUiEvent.parse`, re-emits the wrapped {kind, payload} envelope
// using each payload's `toJson`, and writes the result back as JSON
// on stdout. The harness MUST be a pure-Dart program (no Flutter
// engine dep) so the test can run without a full Flutter SDK.
//
// ``events.dart`` is copied into the same directory as this harness
// (see ``_build_dart_project``) so the relative import resolves
// without ``dart pub get`` fetching the Flutter SDK to satisfy
// forge_canvas's transitive deps. Cross-package relative imports
// aren't legal Dart, hence the copy.
import 'dart:convert';
import 'dart:io';
import 'events.dart';

Map<String, dynamic> _wrap(AgUiEvent event) {
  // ``payload`` is the sealed subclass's underlying value (e.g.
  // ``HitlResponse``). Cast via dispatch on kind — matches the parse
  // factory's set of cases byte-for-byte.
  Map<String, dynamic> payload;
  switch (event.kind) {
    case 'ag-ui-payload':
      payload = (event as AgUiPayloadEvent).payload.toJson();
    case 'agent-state':
      payload = (event as AgentStateEvent).payload.toJson();
    case 'hitl-response':
      payload = (event as HitlResponseEvent).payload.toJson();
    case 'mcp-ext-payload':
      payload = (event as McpExtPayloadEvent).payload.toJson();
    case 'tool-call-info':
      payload = (event as ToolCallInfoEvent).payload.toJson();
    case 'user-prompt-payload':
      payload = (event as UserPromptPayloadEvent).payload.toJson();
    case 'workspace-activity':
      payload = (event as WorkspaceActivityEvent).payload.toJson();
    default:
      throw StateError('unknown kind: ${event.kind}');
  }
  return {'kind': event.kind, 'payload': payload};
}

void main() async {
  final raw = await stdin.transform(utf8.decoder).join();
  final Map<String, dynamic> corpus = jsonDecode(raw) as Map<String, dynamic>;
  final out = <String, Map<String, dynamic>>{};
  for (final entry in corpus.entries) {
    final env = Map<String, dynamic>.from(entry.value as Map);
    final parsed = AgUiEvent.parse(env);
    if (parsed == null) {
      throw StateError('parse failed for ${entry.key}: ${jsonEncode(env)}');
    }
    out[entry.key] = _wrap(parsed);
  }
  stdout.write(jsonEncode(out));
}
"""


def _build_dart_project(tmp_root: Path) -> Path:
    """Materialise a self-contained pure-Dart project at ``tmp_root``.

    The generated ``events.dart`` ships in the forge repo at
    ``packages/forge-canvas-dart/lib/src/generated/events.dart``; we
    copy just that single file (along with the harness) into the
    tempdir so the harness's ``import 'events.dart'`` resolves
    without invoking the real Flutter build. Cross-package relative
    imports aren't legal Dart, so the file MUST sit next to the
    harness rather than being imported from the source package via
    a relative path. A Flutter SDK install would be ~3 GB just to
    compile a pure-Dart file the harness already has on disk.

    Returns the path to the harness ``.dart`` file ready to ``dart run``.
    """
    events_src = (
        Path(__file__).resolve().parent.parent
        / "packages"
        / "forge-canvas-dart"
        / "lib"
        / "src"
        / "generated"
        / "events.dart"
    )
    if not events_src.is_file():
        raise FileNotFoundError(
            f"forge-canvas-dart's generated events.dart missing at {events_src!s}; "
            "regenerate via ``python -m forge.codegen.event_union``"
        )
    test_proj = tmp_root / "harness"
    test_proj.mkdir()
    pubspec = test_proj / "pubspec.yaml"
    # Minimal pubspec so ``dart run`` doesn't bail on the missing
    # config — no deps beyond the dart core library because
    # events.dart only uses Dart's collections + json.
    pubspec.write_text(
        "name: canvas_contract_harness\n"
        "environment:\n"
        "  sdk: '>=3.4.0 <4.0.0'\n",
        encoding="utf-8",
    )

    # Co-locate events.dart with the harness so the relative import
    # works without ``package:`` URIs.
    shutil.copy(str(events_src), str(test_proj / "events.dart"))
    harness = test_proj / "harness.dart"
    harness.write_text(_DART_HARNESS, encoding="utf-8")
    return harness


@pytest.mark.skipif(
    not _have_dart(),
    reason=(
        "dart not on PATH — skipping the canvas-decoder Dart runtime "
        "contract. CI hosts with Flutter installed should cover this; "
        "test SKIPS rather than passing silently so the gap is visible."
    ),
)
class TestDartRoundTrip:
    """Every corpus envelope must round-trip through the Dart sealed-
    class parser byte-identically to its Pydantic counterpart. A drift
    here means a Flutter client would mis-parse a frame the backend
    just emitted — the failure mode Initiative #4 closed for the
    structural surface and Initiative #9 closes for the runtime
    contract.
    """

    def test_dart_envelope_matches_pydantic(self, pydantic_adapter, tmp_path: Path):
        # Build the Pydantic-side expected output map once. Re-using the
        # same fixture so the assertion is "Dart matches Pydantic" rather
        # than "Dart matches a hand-rolled corpus" — that way an emitter
        # drift on the Pydantic side also surfaces here.
        expected: dict[str, str] = {}
        for kind, envelope in CORPUS.items():
            parsed = pydantic_adapter.validate_python(envelope)
            expected[kind] = _canonical(parsed.model_dump(mode="json"))

        harness = _build_dart_project(tmp_path)
        result = subprocess.run(
            ["dart", "run", str(harness)],
            input=json.dumps(CORPUS),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            cwd=str(harness.parent),
        )
        assert result.returncode == 0, (
            f"dart run failed (exit {result.returncode}):\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
        try:
            dart_out: dict[str, dict] = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"dart harness produced non-JSON output: {e}\nRaw: {result.stdout!r}"
            ) from e

        mismatches: list[str] = []
        for kind in CORPUS:
            actual = _canonical(dart_out.get(kind, {}))
            if actual != expected[kind]:
                mismatches.append(
                    f"  {kind}:\n"
                    f"    pydantic: {expected[kind]}\n"
                    f"    dart:     {actual}"
                )
        assert not mismatches, "Dart ↔ Pydantic envelope drift:\n" + "\n".join(mismatches)


# ----------------------------------------------------------------------
# TypeScript / Vue / Svelte runtime contract
# ----------------------------------------------------------------------


def _have_node() -> bool:
    return shutil.which("node") is not None


_TS_HARNESS = r"""
// Pure-Node harness for the canvas-vue / canvas-svelte event-union
// runtime contract. The generated events.ts has two runtime
// helpers: ``getEventKind(event) → event.kind`` and
// ``assertUnreachable(_)``. We extract them via a deliberately
// narrow regex (lines starting with `export function ...` plus the
// next non-empty line) so we don't have to ship a full TS-to-JS
// compiler in the test path — adding tsc / tsx / ts-node would
// require a network-online ``npx`` invocation and ~50 MB of node
// modules per CI run.
//
// The runtime invariant we verify: for each corpus envelope, the
// shipped ``getEventKind`` returns the envelope's ``kind`` field
// byte-for-byte. This is the contract the AgUiClient ts shim
// documents — a JSON-decoded ``{kind, payload}`` envelope IS the
// typed event union when ``kind`` is one of the declared
// discriminator slugs.

const fs = require('fs');

const srcPath = process.argv[2];
const tsSrc = fs.readFileSync(srcPath, 'utf-8');

// Match exactly:
//   export function getEventKind(event: AgUiEvent): AgUiEventKind {
//     return event.kind;
//   }
// Capture the body so we can rebuild a JS-callable version. Use
// non-greedy matching to stop at the first ``}`` at column 0 —
// shipping ``getEventKind`` is a one-line body so this is robust
// without a TS parser.
const getKindMatch = tsSrc.match(
  /export\s+function\s+getEventKind\s*\([^)]*\)\s*:\s*[A-Za-z]+\s*\{\s*([^}]+?)\s*\}/
);
if (!getKindMatch) {
  throw new Error(
    'getEventKind not found in events.ts — codegen drift would mean ' +
    'the canvas-vue/svelte runtime contract is no longer enforceable.'
  );
}
// Strip the parameter type annotation (``event: AgUiEvent``) to leave
// a plain JS function. We re-wrap with a one-arg ``event``.
const body = getKindMatch[1];
// eslint-disable-next-line no-new-func
const getEventKind = new Function('event', body);

const corpus = JSON.parse(fs.readFileSync(0, 'utf-8'));
const out = {};
for (const [k, env] of Object.entries(corpus)) {
  out[k] = { kind: getEventKind(env), payload: env.payload };
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(
    not _have_node(),
    reason=(
        "node not on PATH — skipping the TypeScript (Vue+Svelte) runtime "
        "contract. The canvas-vue + canvas-svelte event modules are "
        "byte-identical (proven by test_event_union_codegen); a single "
        "Node-driven check exercises both at once. CI hosts with Node "
        "should cover this; test SKIPS rather than passing silently."
    ),
)
class TestTypeScriptRoundTrip:
    """The Vue + Svelte canvas packages share a byte-identical
    ``events.ts`` (proven byte-equal by ``test_event_union_codegen``).
    The runtime surface they expose is ``getEventKind`` — a trivial
    ``return event.kind`` — plus the type-only union. The real contract
    is that the canonical ``kind`` discriminator on the Pydantic-emitted
    envelope IS the same string ``getEventKind`` returns at runtime;
    that pin is what this test enforces.

    Future work / known gap: the canvas-vue and canvas-svelte
    packages punt actual parse-and-validate logic to user-supplied
    ``parser`` callbacks (per the AgUiClient docs), so there's no
    package-shipped parse function to test against. Once such a parse
    helper lands in the canvas packages, expand this test to
    round-trip the corpus through it the way the Dart test does.
    """

    @pytest.mark.parametrize("package", ["canvas-vue", "canvas-svelte"])
    def test_node_kind_matches_envelope(self, tmp_path: Path, package: str):
        events_ts = (
            Path(__file__).resolve().parent.parent
            / "packages"
            / package
            / "src"
            / "generated"
            / "events.ts"
        )
        assert events_ts.is_file(), (
            f"missing generated events.ts for {package!r} — regenerate via "
            "``python -m forge.codegen.event_union``"
        )
        harness = tmp_path / f"harness-{package}.js"
        harness.write_text(_TS_HARNESS, encoding="utf-8")

        result = subprocess.run(
            ["node", str(harness), str(events_ts)],
            input=json.dumps(CORPUS),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, (
            f"node harness failed (exit {result.returncode}) for {package!r}:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        try:
            out: dict[str, dict] = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise AssertionError(
                f"node harness produced non-JSON: {e}\nRaw: {result.stdout!r}"
            ) from e

        mismatches: list[str] = []
        for kind, envelope in CORPUS.items():
            if out.get(kind, {}).get("kind") != envelope["kind"]:
                mismatches.append(
                    f"  {kind}: expected kind={envelope['kind']!r}, "
                    f"got {out.get(kind, {}).get('kind')!r}"
                )
            if out.get(kind, {}).get("payload") != envelope["payload"]:
                mismatches.append(
                    f"  {kind}: payload diverged"
                )
        assert not mismatches, (
            f"TypeScript ({package}) runtime drift from corpus:\n" + "\n".join(mismatches)
        )

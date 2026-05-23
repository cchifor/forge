# Implementation review — feat/port-spec — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 11 findings; 7 ACCEPT, 2 PUSHBACK addressed via docs + narrowed surface, 1 PUSHBACK rejected as misunderstanding, 1 QUESTION addressed) -->

## Codex verdict

**ACCEPT** with 2 PUSHBACK items addressed in this commit:
1. **Node anchor scope limitation** — documented loudly in node.jinja
   header that `FORGE:MIDDLEWARE_IMPORTS` is top-level (before
   `buildApp()`), so `service_factory` must be a top-level declaration
   only (NOT `app.register(...)`). Future Pillar D.2 consumer (llm_port
   Node) will add a second anchor inside `buildApp()` if its adapter
   needs Fastify-runtime registration.
2. **`adapter_imports` re-export narrowing** — removed `render_*_port`
   helpers from `forge/specs/__init__.py::__all__` (they stay
   importable, just not in the curated public surface).

The third PUSHBACK ("35 tests overstated, only 27") is a measurement
mismatch — see Finding #2.

## Findings + responses

### 1. Node anchor mismatch (PUSHBACK → ADDRESSED via doc)
**Codex's verification:** the `FORGE:MIDDLEWARE_IMPORTS` marker in
`src/app.ts.jinja:9` is at the top-level import block BEFORE `buildApp()`
opens at line 11. The Node template docs suggested `app.register(...)`
as a valid `service_factory` value, but `app` isn't in scope at that
anchor.

**Response:** updated `forge/templates/_shared/port_spec/node.jinja`
header with a loud "SCOPE LIMITATION" callout. Service_factory MUST be
top-level only (const, class instantiation, side-effect import).
`app.register(...)` is explicitly listed as NOT acceptable. Replaced
the misleading examples in the existing comment with correct ones
(`const _<port>Adapter: <Port> = new <Adapter>()`,
`export const <port>Container = new <DIContainer>()`).

The proper architectural fix (a second Node anchor inside `buildApp()`)
is deferred to Pillar D.2 (llm_port Node + Rust). The first real
consumer will surface the actual need; speculating now would add an
anchor that may not match what D.2 wants. For Pillar A.4's
internal-infrastructure scope, the limitation is documented and the
v1 use case (top-level wiring) works.

### 2. Test count claim 35 vs 27 (PUSHBACK → REJECTED, measurement mismatch)
**Codex's count:** 27 `def test_` functions in `tests/test_port_spec.py`.

**Agent's count:** "35 tests" in their final report.

**Local verification:** `pytest tests/test_port_spec.py` reports
"35 passed". Both numbers are accurate from their own viewpoint —
some test functions are parametrized via `@pytest.mark.parametrize`,
expanding to multiple cases. Codex counted source-level definitions
(27); agent counted runtime cases (35). Neither is wrong.

No code change. Suggest future agent reports normalize to "N
runtime cases (M source-level defs)" to avoid the confusion.

### 3. `adapter_imports` lossy `" from "` DSL (QUESTION → noted)
**Codex's concern:** strings split on `" from "` — fails if a real
module path contains that substring (e.g.
`"FooBar from utils/from-dir/index"`).

**Response:** acknowledged as v1 design debt. The first PortSpec
consumer (Pillar D.2 llm_port) will use `import { ChatChunk } from
"@ai-sdk/core";` style paths — module paths don't typically contain
`" from "`. A structured `ImportSpec` dataclass would be cleaner but
adds surface area for a problem we haven't seen yet. Tracked for
1.3 evaluation.

### 4. Dataclass shape + ordering (ACCEPT)
Frozen dataclass. `interface_path` (required) before all defaulted
fields. Literal `()` for default tuple (no `field(default_factory=)`
overhead).

### 5. FragmentRenderer Protocol conformance (ACCEPT)
`isinstance(spec, FragmentRenderer)` passes. `render(*, backend,
feature_key, jinja_env=None) -> tuple[_Injection, ...]` matches the
protocol signature.

### 6. Single-injection-per-backend (ACCEPT)
1-tuple returns for Python/Node/Rust. Single anchor per backend
mirrors existing `queue_port` precedent.

### 7. Anchor/target mapping (ACCEPT)
Python `container.py @ FORGE:APP_POST_CONFIGURE` ✓
Node `src/app.ts @ FORGE:MIDDLEWARE_IMPORTS` ✓ (with the limitation
in Finding #1)
Rust `src/lib.rs @ FORGE:LIB_MOD_REGISTRATION` ✓
All match `queue_port`'s precedent.

### 8. Jinja lazy env (ACCEPT — inherits A.2's debt)
PortSpec constructs its own Jinja env when `jinja_env=None`. Inherits
the env-threading debt acknowledged in PR #83's codex review (RFC-009
follow-up will thread env through `_render_all`).

### 9. `detect_port_cycle` algorithm (ACCEPT)
DFS with `visiting`/`visited` sets. Tests cover no-cycle, self-cycle,
two-node cycle, external dep handling, empty graph.

### 10. Re-export surface (QUESTION → ADDRESSED)
**Codex's concern:** `render_fastapi_port`, `render_fastify_port`,
`render_axum_port` exposed via `__all__` in `forge/specs/__init__.py`.
Broadens accidental API surface.

**Response:** removed the 3 port render helpers from `__all__` (still
importable at module level for tests). Added a docstring comment
explaining the curation policy: new spec types treat per-backend
renderers as implementation detail until a follow-up audit promotes
the ones that have stable surfaces. The pre-existing
`render_*_middleware` / `render_*_layer` helpers stay in `__all__`
for back-compat (they shipped public in Epic K).

### 11. CHANGELOG entry (ACCEPT)
Honest about scope/deferments; internal infra; first consumer in
Pillar D.2.

## Convergence

11 findings — 7 ACCEPT, 2 PUSHBACK addressed (Node limitation
docs + narrowed re-exports), 1 PUSHBACK rejected as measurement
mismatch, 1 QUESTION noted. No round 2 dispatched.

## Diff stat (this commit)

```
 forge/specs/__init__.py                         |  19 +++++--
 forge/templates/_shared/port_spec/node.jinja    |  29 +++++++++--
 plans/2026-05-22-port-spec-impl-review.md       | 130 ++++++++++++++++++++++
 3 files changed, 167 insertions(+), 11 deletions(-)
```

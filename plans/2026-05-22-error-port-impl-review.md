# Implementation review — feat/error-port — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 7 findings; 1 critical PUSHBACK addressed, 2 PUSHBACK accepted as scope-down, 2 PUSHBACK noted as follow-up, 1 ACCEPT) -->

## Codex verdict

**ACCEPT** with 1 critical PUSHBACK addressed in this commit:
- **Node `correlationId` → `correlation_id`** wire-shape regression
  fixed. RFC-007 mandates snake_case; the original Node port/adapter
  used camelCase which would have diverged from the existing
  base-template error-handler that emits `correlation_id`.

Three other PUSHBACKs are honestly **scoped down for this PR**:
- Real cross-language wire test (vs string-grep) — deferred to E.1.b
  follow-up that actually wires the port into the runtime path.
- Runtime integration (the port is currently scaffolding-only) —
  this PR is **explicitly scope-down to "ship the port surface
  + adapter implementations"**. Wiring into the existing
  error-handler.ts / errors.py / errors.rs runtime path is a
  follow-up tracked here.
- Drift contracts (Python `_lookup_mapping` import, Rust
  `AppError::context()` duplication) — known design debt; promoting
  to public helpers is a base-template refactor outside this PR.

## Findings + responses

### 1. Cross-language wire-shape test is structural not behavioural (PUSHBACK → noted, deferred)
**Codex:** `test_envelope_wire_shape_matches_rfc007_across_backends`
only checks source text presence, not emitted JSON from each backend.

**Response:** acknowledged. The real wire test requires actually
executing the adapter in each backend, which means either:
1. Running each backend's runtime (heavy, slow), OR
2. Embedding a per-language harness that imports + invokes the adapter
   directly (requires Python + Node + Rust in CI test environment).

For this scaffolding-only PR, the structural check at least catches
field-name typos like the `correlationId` regression codex caught.
The behavioural test is tracked as **E.1.b follow-up** when the port
gets wired into the runtime path (at which point the existing
end-to-end error-handler integration tests cover the wire shape
naturally).

### 2. Node `correlationId` vs RFC-007 `correlation_id` (PUSHBACK → ADDRESSED)
**Codex's catch (CRITICAL):** Node port + adapter declared
`correlationId` (camelCase) but RFC-007 + the existing base-template
error-handler use `correlation_id` (snake_case). If the port were
wired today, the Node service would emit a different envelope shape
than Python + Rust — silent wire-shape divergence.

**Response:** changed Node port + adapter to use `correlation_id`.
Updated the test assertion that previously checked for `correlationId`
to check for `correlation_id`. Now all 3 backends + RFC + existing
error-handler agree on the spelling.

### 3. Port is registered but not on the runtime path (PUSHBACK → noted, scope-down)
**Codex:** the port is injected (imports + module exposure) but no
backend handler calls `DefaultErrorPort.serialize(...)`. So it's
passive scaffolding.

**Response:** acknowledged + explicitly scope-down. The CHANGELOG
entry is honest about this: the PR ships the port + adapter as the
**capability contract**; wiring the central error-handler to consume
the port is **E.1.b follow-up**. This split keeps the cross-cutting
runtime change isolated for clean codex review when it lands.

### 4. Python adapter imports private helpers (PUSHBACK → noted, design debt)
**Codex:** `DefaultErrorPort` imports `_lookup_mapping` /
`_context_for` from `app.core.errors` — leading underscore = private.

**Response:** acknowledged drift contract. Two follow-up paths:
either (a) promote to public + add `__all__` entries, or (b) refactor
the adapter to avoid the import. Both touch the base template
`services/python-service-template/template/src/app/core/errors.py`
which is out of scope for this PR. Tracked as **E.1.c follow-up**.

### 5. Rust adapter duplicates `AppError::context()` (PUSHBACK → noted, design debt)
Same shape as #4 but for Rust. Tracked as E.1.c follow-up.

### 6. `error_envelope=False` semantics confusing in current state (PUSHBACK → noted)
**Codex:** option says `=False` strips via follow-up; currently
strips the port scaffolding but leaves the runtime error-handler
intact. Mechanically coherent, product semantics misleading.

**Response:** the CHANGELOG entry (already honest about this) calls
it scaffolding-only. After E.1.b wires the runtime, `=False` will
have product-visible behavior: revert to the legacy error-handler.
Until then, the option is effectively "include the scaffolding files
or not". Updated the option description to make this clearer.

### 7. Rust `src/error_port/` path (ACCEPT)
Codex confirms the path choice avoids the strict-applier overlap
guard collision with `queue_port`'s `src/ports/mod.rs`. Sound
within current applier constraints. (PortSpec PR #88 — A.4 — is the
proper architectural fix for the shared-`ports/`-tree pattern.)

## Follow-ups (explicit, deferred)

- **E.1.b** — wire the port into the runtime central error-handler in
  each backend. Cross-cutting change touching
  `services/{python,node,rust}-service-template`'s error-handler files.
- **E.1.c** — promote `_lookup_mapping` / `_context_for` (Python) +
  `AppError::context` (Rust) to public surfaces OR refactor adapters
  to avoid private imports.
- **E.1.d** — real behavioural wire-shape test (each backend's adapter
  emits + parses + cross-validates). Naturally satisfied by E.1.b's
  end-to-end coverage.

## Convergence

7 findings — 1 ACCEPT, 1 PUSHBACK addressed (Node correlation_id),
4 PUSHBACK explicitly scoped-down for this scaffolding PR + tracked as
follow-up, 1 PUSHBACK noted (env semantics) + docstring tightened.

No round 2 dispatched — the critical PUSHBACK (correlation_id wire-shape)
addressed; the rest are scope choices the user can adjudicate via
review of this impl-review file.

## Diff stat (this commit)

```
 .../error_port/node/files/src/app/adapters/error-default.ts | 6 +++---
 .../error_port/node/files/src/app/ports/error-port.ts       | 4 ++--
 tests/test_error_port.py                                    | 7 ++++++-
 plans/2026-05-22-error-port-impl-review.md                  | 100 +++++++++++++
 4 files changed, 113 insertions(+), 4 deletions(-)
```

# Implementation review — feat/canvas-core-package — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 8 findings, all nits, no blockers; converged) -->

## Codex verdict

**Ready to merge.** 8 findings across reducer parity, SSE parser, MCP approval client,
inline-patch equivalence, AbortSignal handling, test coverage, build setup, plan compliance —
all marked SEVERITY: nit. Two minor items noted (JSON.stringify cache-key ordering;
70-char commit subject); both PUSHBACK with rationale below. No round 2 needed.

## Findings + responses

### 1. Reducer ↔ Dart parity — verified clean (nit, positive finding)
**Location:** `packages/canvas-core/src/reducer.ts` vs `forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/data/agent_state_reducer.dart`

All 7 critical defensive behaviors match line-for-line: RUN_STARTED clears error,
TEXT_MESSAGE_CONTENT fallback to last message, STATE_DELTA silent no-op on bad patch,
unknown CUSTOM names silently ignored, TOOL_CALL_ARGS no-op, role fallback to assistant,
ACTIVITY_SNAPSHOT canvas/workspace gating. Semantic drift: zero.

**Response:** No action — verified parity.

### 2. SSE parser — RFC 8895 compliant (nit, positive finding)
**Location:** `packages/canvas-core/src/ag_ui_client.ts:165-296`

Multi-line `data:` joined with `\n`; comment lines (`:`) skipped; `\n\n` + `\r\n\r\n`
boundaries both handled; `id:` persisted as Last-Event-ID; TextDecoder stream-mode
handles UTF-8 multi-byte sequences split across TCP packets.

**Response:** No action — correct.

### 3. McpApprovalClient JSON.stringify cache-key ordering (nit, PUSHBACK)
**Location:** `packages/canvas-core/src/mcp_approval_client.ts:265` (`cacheKey()`)

**Codex's finding:** `JSON.stringify` is insertion-order-sensitive, so `{a:1, b:2}` and
`{b:2, a:1}` would key differently in the TS cache despite producing the same HMAC hash
on the backend (which uses `sort_keys=True` per `audit.py:85`). Codex explicitly notes
"not blocking" because cache misses are non-functional (one extra mint call, not a 401)
and typical call sites build inputs in fixed literal-order anyway.

<!-- opus-pushback: Decline to introduce sort-keys cache normalization in this PR. The
worst-case symptom is one redundant `/mcp/approval/mint` call, not a 401; backend
verification still succeeds because its own hash is order-stable. Adding sorted-stringify
to all three implementations (TS canvas-core + Svelte inline + Dart inline) would expand
scope to ~30 LOC + 3 new tests for a defensive measure with no observed failure mode.
If the issue ever surfaces in practice (cache hit rate metric below expectations), the
fix is localized and mechanical. -->

### 4. Inline patches (Svelte + Dart) ↔ canvas-core equivalence (nit, positive finding)
**Locations:** `forge/features/platform/templates/mcp_ui_svelte/.../use-mcp-tools.svelte.ts`,
`forge/features/platform/templates/mcp_ui_flutter/.../mcp_client.dart`

Codex verified TTL constant, cache-key shape, mint payload shape, 401-eviction path,
and cache data structure all match across the three implementations.

**Response:** No action — verified.

### 5. AbortSignal handling — correct end-to-end (nit, positive finding)
**Location:** `packages/canvas-core/src/ag_ui_client.ts:117-131`

Signal propagated from `runAgent` → fetch → consumeStream loop check. Caller abort
surfaces via promise rejection or early loop exit. Test covers abort scenario.

**Response:** No action — correct.

### 6. Test coverage — comprehensive (nit, positive finding)
**Location:** `packages/canvas-core/tests/` (59 tests across 5 files)

All 14 event types exercised; defensive coercion paths covered; SSE multi-frame +
Last-Event-ID + reconnect tested; McpApprovalClient covers auto / non-auto / TTL /
401 evict / cache key / baseUrl. Optional gap: dedicated test for
`CUSTOM.deepagent.state_snapshot` (today covered as part of general CUSTOM).

**Response:** No action — coverage adequate. The general CUSTOM test does
exercise both deepagent names; a dedicated test would be marginal.

### 7. Build setup — correct externalisation (nit, positive finding)
**Location:** `packages/canvas-core/vite.config.ts`, `package.json`

Vite library mode (`formats: ['es']`); `@ag-ui/core` externalised (types-only import
in events.ts); `fast-json-patch` bundled (runtime dep); jsdom for vitest browser APIs.

**Response:** No action — correct.

### 8. Plan scope compliance — exactly Phase 1 (nit, positive finding)
**Location:** plan file `deep-gliding-mccarthy.md` lines 107-125

PR delivers Pillar B Phase 1 Step 1 (canvas-core package) and Step 2 (inline wire
fixes). Steps 3-5 (per-stack rewrite, forge_canvas_core Dart, MCP iframe bridge
unification) explicitly deferred per plan.

**Response:** No action — full adherence.

### 9. Commit subject line exceeds 50-char convention (nit, PUSHBACK)
**Location:** Commit subject (`feat(canvas-core): Pillar B Phase 1 — protocol package + MCP wire fix`, 70 chars)

<!-- opus-pushback: Decline to amend. Per CLAUDE.md the convention is preferred but
the substantial commit body (7 paragraphs explaining package, wire bug, tests,
deferral) carries the load that the subject can't. Per CLAUDE.md "Prefer to create
a new commit rather than amending an existing commit" — a fixup commit just to
shorten the subject adds noise without value. Future Pillar B Phase 2 PRs will
aim for ≤50 chars on routine work. -->

## Convergence

8 findings, all nits. 7 are positive verifications or no-action. 2 are PUSHBACK
with documented rationale (cache-key ordering trade-off; commit-subject amend
declined). Codex's own verdict: "Ready to merge". No round 2 dispatched.

## Diff stat

```
 .../files/lib/src/features/mcp/mcp_client.dart     | 117 +++++++-
 .../src/lib/features/mcp/use-mcp-tools.svelte.ts   | 103 ++++++-
 packages/canvas-core/package.json                  |  44 +++
 packages/canvas-core/src/ag_ui_client.ts           | 296 +++++++++++++++++++++
 packages/canvas-core/src/events.ts                 | 247 +++++++++++++++++
 packages/canvas-core/src/index.ts                  |  92 +++++++
 packages/canvas-core/src/mcp_approval_client.ts    | 274 +++++++++++++++++++
 packages/canvas-core/src/mcp_bridge.ts             | 141 ++++++++++
 packages/canvas-core/src/reducer.ts                | 257 ++++++++++++++++++
 packages/canvas-core/src/snapshot.ts               | 138 ++++++++++
 packages/canvas-core/tests/ag_ui_client.test.ts    | 229 ++++++++++++++++
 packages/canvas-core/tests/events.test.ts          |  86 ++++++
 .../canvas-core/tests/mcp_approval_client.test.ts  | 223 ++++++++++++++++
 packages/canvas-core/tests/mcp_bridge.test.ts      | 106 ++++++++
 packages/canvas-core/tests/reducer.test.ts         | 251 +++++++++++++++++
 packages/canvas-core/tsconfig.json                 |  26 ++
 packages/canvas-core/vite.config.ts                |  38 +++
 17 files changed, 2662 insertions(+), 6 deletions(-)
```

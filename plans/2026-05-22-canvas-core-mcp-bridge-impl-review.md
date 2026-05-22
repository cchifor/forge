# Implementation review — feat/canvas-core-mcp-bridge-helper — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 13 findings; 10 ACCEPT, 3 PUSHBACK addressed, 1 QUESTION) -->

## Codex verdict

**ACCEPT** with 3 PUSHBACK items addressed in this commit:
1. `UpstreamAppBridge.sendSandboxResourceReady` made optional (no longer
   type-breaks downstream mock implementations).
2. `connect()` promise rejection now explicitly `.catch()`'d.
3. New test asserting `transportCtor` receives `iframe.contentWindow` as
   BOTH source and target (exact-args coverage).

Plus 1 additional defensive test for the legacy-mock case (bridge stub
that predates `sendSandboxResourceReady`).

## Findings + responses

### 1. API shape (ACCEPT)
Callback names align with upstream handlers; covers both Vue + Svelte
template patterns + reactive `sendToolInput`.

### 2. Constructor injection guarantee — no upstream dep in canvas-core (ACCEPT)
Verified: no `@modelcontextprotocol/ext-apps` import in canvas-core src
or package.json. Only doc-comments mention it.

### 3. `UpstreamAppBridge.sendSandboxResourceReady` — type-breaking required method (PUSHBACK → ADDRESSED)
**Codex's concern:** adding a required method to a public interface
silently breaks downstream `UpstreamAppBridge` mock/custom implementations.
The real `@modelcontextprotocol/ext-apps` `AppBridge` has it, so production
consumers are fine; but a downstream consumer's hand-rolled stub
implementing only `oninitialized`/`onmessage`/`onopenlink`/etc. would
suddenly fail to satisfy the interface.

**Response:** changed signature to `sendSandboxResourceReady?(...)` —
optional. `mountMcpExtBridge` now guards with
`typeof bridge.sendSandboxResourceReady === 'function'` before calling.
Sandbox-resource activities against a bridge missing the method become
a no-op rather than a TypeError. Added test
`skips sendSandboxResourceReady when the upstream bridge lacks the method (legacy mock support)`
asserting the legacy-mock path works cleanly.

### 4. Unmount-during-connect race guard (ACCEPT)
`cancelled` flag set by `cleanup()`; post-connect `.then()` checks it
before `sendSandboxResourceReady`. Explicit + tested.

### 5. Idempotent cleanup (ACCEPT)
`teardownCalled` guard ensures one `teardownResource` call max. Tested.

### 6. `html` as gate for sendSandboxResourceReady (QUESTION → noted)
Codex notes the `typeof html === 'string'` gate is rigid; future
CSP-only updates would need a revisit. Reasonable per template precedent.
Not addressed in this PR — wait for an upstream contract change to
justify a CSP-only signaling mode.

### 7. Throw on null contentWindow (ACCEPT)
Programmer error caught loudly. Tested with detached iframe.

### 8. Re-export consistency vue + svelte (ACCEPT)
Runtime + type exports identical across canvas-vue and canvas-svelte
protocol entry points.

### 9. Missing transportCtor exact-args test (PUSHBACK → ADDRESSED)
Added test `constructs PostMessageTransport with the iframe contentWindow as both source AND target`
that records the args the transport ctor receives and asserts they equal
`iframe.contentWindow` for both source AND target (and are the same
window).

### 10. Unhandled connect() rejection (PUSHBACK → ADDRESSED)
**Codex's concern:** `void bridge.connect(transport).then(...)` had no
`.catch()`, so a rejected connect surfaces as unhandled promise rejection.

**Response:** added `.catch(() => {})` to swallow the rejection (with a
comment explaining the rationale: connect failures surface to the user
via the iframe never loading; no useful action the helper can take).
Added test `swallows a rejected connect() promise (no unhandled rejection)`
asserting `cleanup()` still works cleanly after a rejected connect.

### 11. Version bump consistency (ACCEPT)
canvas-core 1.0.0-alpha.1 → 1.0.0-alpha.2. canvas-vue + canvas-svelte
depend on `^1.0.0-alpha.1` which semver-satisfies alpha.2.

### 12. CHANGELOG (ACCEPT)
New `packages/canvas-core/CHANGELOG.md` with 1.0.0-alpha.2 entry.

### 13. Worktree artifacts (CLEAN)
No stray worktree paths in diff.

## Convergence

13 findings — 10 ACCEPT, 3 PUSHBACK addressed via this commit, 1
QUESTION noted (html-gate rigidity, future-looking). No round 2
dispatched — all actionable feedback addressed; the QUESTION is a
design conversation for when the upstream contract evolves.

## Diff stat (final)

```
 packages/canvas-core/CHANGELOG.md             |  25 ++
 packages/canvas-core/package.json             |   2 +-
 packages/canvas-core/src/index.ts             |   6 +
 packages/canvas-core/src/mcp_bridge.ts        | 220 +++++++++++++++++
 packages/canvas-core/tests/mcp_bridge.test.ts | 422 +++++++++++++++++++++++++++
 packages/canvas-svelte/src/protocol.ts        |   6 +
 packages/canvas-vue/src/index.ts              |   6 +
 7 files changed, 686 insertions(+), 1 deletion(-)
```

Plus this impl-review file.

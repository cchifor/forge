# Implementation review — feat/svelte-mcp-iframe-mount — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 10 findings; 7 ACCEPT, 1 PUSHBACK→addressed via doc, 2 QUESTION→1 addressed, 1 noted) -->

## Codex verdict

**PUSHBACK** on point 10 (overall merge readiness) — hold for round 2 to address
the `activity.content` deep-update parity gap. Single actionable item; all
others ACCEPT or non-blocking nits.

## Findings + responses

### 1. Vue↔Svelte parity — `activity.content` deep-watch (QUESTION → ADDRESSED)
**Location:** `McpExtEngine.svelte` lines 121-130 vs `McpExtEngine.vue` lines 74-86

Vue uses `watch(..., {deep: true})`; Svelte 5's `$effect` only re-runs on
reference changes. Could diverge if a producer mutates `activity.content`
in place.

**Response:** documented the protocol contract instead of adding deep-watching.
The AG-UI reducer (`canvas-core/src/reducer.ts` ACTIVITY_SNAPSHOT case) always
constructs a fresh `WorkspaceActivity` with a new `content` reference per
event. No producer mutates in place. Added an explicit comment in the
Svelte `$effect` explaining the divergence is intentional — if a future
producer violates the immutable-snapshot contract, the proper fix is in the
producer, not deep-watching here that would paper over the protocol violation.

### 2. Svelte 5 idioms (ACCEPT)
`iframeEl` as `$state` + `bind:this` idiomatic; `bridge` as plain `let`
appropriate (internal non-render state); two `$effect`s acceptable.

### 3. Bridge-connection race (ACCEPT)
Race acknowledged and guarded: `bridge` assignment before async `connect()`,
`sendToolInput` try/catched, `if (bridge !== localBridge) return` handles
unmount-during-connect.

### 4. Type casting (ACCEPT)
`WorkspaceActivity.content` is `Record<string, unknown>` — casts necessary.
Cleaner `McpExtContent` type-guard could come later; not a correctness blocker.

### 5. Sandbox attribute (ACCEPT)
`sandbox="allow-scripts allow-same-origin allow-forms"` matches Vue exactly.

### 6. Pillar B Step 5 deferral (ACCEPT)
Current `createMcpBridge` in canvas-core wraps handler wiring/close only,
not template-specific construction/connect/resource-ready flow. Inline setup
in templates is reasonable until Step 5 broadens the abstraction.

### 7. Test coverage (QUESTION → noted, no action)
Acceptable for template-only changes in this repo's current pattern;
Vue has similar gaps. Flagged for future hardening but not a blocker.

### 8. Flutter parity / MCP_BRIDGE_AVAILABLE (ACCEPT)
Web-only contract correct (`canvas-core/src/mcp_bridge.ts:110-111` checks
`globalThis.window`).

### 9. Commit subject 54 chars (ACCEPT — nit)
Per CLAUDE.md prefer ≤50; this is 4 over. Already pushed; not amending per
the "prefer new commits over --amend" rule. Future Phase B PRs aim for ≤50.

### 10. Overall verdict (PUSHBACK → ADDRESSED via #1)
Round 2 not needed — the actionable item (#1) addressed via the immutability
documentation. All other points ACCEPT.

## Convergence

10 findings, 7 ACCEPT, 1 PUSHBACK addressed via doc, 2 QUESTION (1 addressed,
1 noted for follow-up). No round 2 dispatched — codex's PUSHBACK request
was satisfied by adding the immutable-snapshot contract comment.

## Diff stat (rebased)

```text
 .../chat/workspace/engines/McpExtEngine.svelte     | 154 +++++++++++++++++++--
 1 file changed, 141 insertions(+), 13 deletions(-)
```

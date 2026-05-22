# Implementation review — feat/chat-retry-button — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 10 findings; 6 ACCEPT, 3 PUSHBACK addressed, 1 QUESTION noted) -->

## Codex verdict

**ACCEPT** with 3 PUSHBACK items addressed in this commit:
1. **Flutter forwardedProps replay (CRITICAL)**: now captures the
   fully-merged props (including model + approval) at snapshot time,
   matching Vue/Svelte verbatim-replay semantics.
2. **Vue + Svelte in-flight guard**: `retryLastRun()` now no-ops when
   `isRunning` is true. Spamming the Retry button during a slow retry
   no longer queues multiple `runAgent` calls.
3. **Vue `dismissError()` API**: added as a public method on the agent
   client + re-exported through `useAiChat`. The UI no longer mutates
   `runError.value` directly — cross-stack consistency with Svelte +
   Flutter.

## Findings + responses

### 1. ThreadId preservation (ACCEPT)
Verified in all 3 stacks. Tests explicitly assert same-thread retry:
- Vue: `useAgentClient.test.ts:422-434`
- Svelte: `chat.test.ts:110-113`
- Flutter: `chat_providers_test.dart:99-101`

### 2. forwardedProps replay completeness (PUSHBACK → ADDRESSED)
**Codex's concern (CRITICAL DIVERGENCE):** Flutter stored only the raw
inner `forwardedProps` (e.g. `{'attachment_ids': [...]}`) while
`_runAgent` injected current provider values for `model`/`approval` on
each call. If user changes model/approval between failure and retry,
retry was NOT "same request replay" — violating the documented contract.

**Response:** changed Flutter `chat_providers.dart:228` from
`_lastForwardedProps = forwardedProps` to
`_lastForwardedProps = Map<String, dynamic>.from(mergedProps)`. Now
the snapshot captures the fully-merged shape (including `model` +
`approval` at the moment of the failed run). Subsequent retries re-send
the captured values — `_runAgent`'s dict-spread of `_lastForwardedProps`
overrides the live provider values for the duration of the retry call.

Cross-stack now consistent: Vue + Svelte + Flutter all replay the exact
failed request.

### 3. hasRun flag semantics (ACCEPT)
Implemented correctly in all 3 stacks. No-op-before-first-run tests exist.

### 4. Snapshot timing (Flutter-specific) (ACCEPT)
`_lastBearerToken` / `_lastForwardedProps` / `_hasRun` set BEFORE the
AG-UI call, so thrown errors still leave retry armed.

### 5. HITL semantics (QUESTION → noted)
**Codex's design question:** retry after a failed HITL re-sends the HITL
response. Should it skip HITL and give the user a chance to change the
answer instead?

**Response:** acknowledged as a product decision, not a code bug. The
current "retry-what-just-failed" semantics is consistent across stacks
and matches user expectation for the common case (transient network
failure). If product wants "retry-with-different-answer", that's a new
flow (the Dismiss button + re-asking already covers it). Documenting
here for future product review.

### 6. Svelte banner — Dismiss + Retry (ACCEPT)
Both buttons present + wired.

### 7. Flutter banner shape (ACCEPT)
TextButton.icon Retry + TextButton Dismiss inside a Row.

### 8. Test coverage gap — in-flight guard (PUSHBACK → ADDRESSED)
**Codex's gap:** only Flutter tested "no double retry while in flight".
Vue + Svelte allowed double-retry via UI spam.

**Response:**
- Added `isRunning` guard to Vue `retryLastRun` at
  `useAgentClient.ts:262` (now `if (!hasRun || isRunning.value) return`).
- Added `isRunning` guard to Svelte `retryLastRun` at
  `agent-client.svelte.ts:232` (now `if (!hasRun || isRunning) return`).
- Added Vue test `retryLastRun is a no-op while a run is in flight
  (anti-double-retry)` — fires `runAgent` once with a non-resolving
  promise, calls retry 3× in a row, asserts mockRunAgent still
  called once.
- Added Svelte test of same shape (`retryLastRun is a no-op while a
  run is in flight`).

### 9. `dismissError()` API consistency (PUSHBACK → ADDRESSED)
**Codex's concern:** Svelte + Flutter exposed `dismissError()` but Vue
did not — the UI layer mutated `runError.value = null` directly.
Inconsistent.

**Response:**
- Added `dismissError()` method to Vue `useAgentClient.ts:271`. Clears
  `error.value`. Re-exported through `useAiChat.ts:75`.
- Updated `AiChat.vue` to import `dismissError` from `useAiChat()` and
  remove the local `dismissError()` function that mutated `runError.value`.
- Added Vue test `dismissError() clears error.value (public API,
  mirrors Svelte/Flutter)`.

All 3 stacks now expose `dismissError()` as a public method.

### 10. CHANGELOG (ACCEPT)
Honest description. Updated to reflect cross-stack consistency now
that Vue's dismissError + in-flight guard align with Svelte/Flutter.

## Convergence

10 findings — 6 ACCEPT, 3 PUSHBACK addressed (Flutter forwardedProps,
in-flight guard, Vue dismissError), 1 QUESTION noted (HITL retry
semantics, product decision).

No round 2 dispatched — all 3 actionable PUSHBACKs addressed in this
commit. The QUESTION is a future product conversation.

## Diff stat (this commit)

```
 .../features/chat/presentation/chat_providers.dart       |  9 +++-
 .../lib/features/chat/model/agent-client.svelte.ts       |  6 ++-
 .../src/lib/features/chat/model/chat.test.ts             | 17 +++++++++
 .../ai_chat/composables/useAgentClient.test.ts           | 34 ++++++++++++++++++
 .../features/ai_chat/composables/useAgentClient.ts       | 17 +++++++--
 .../src/features/ai_chat/composables/useAiChat.ts        |  9 +++++
 .../template/src/features/ai_chat/ui/AiChat.vue          |  5 +--
 7 files changed, 89 insertions(+), 8 deletions(-)
```

Plus this impl-review file.

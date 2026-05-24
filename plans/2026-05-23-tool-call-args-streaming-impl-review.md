# Implementation review — feat/chat-tool-call-args-streaming — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 12 findings; 10 ACCEPT, 2 PUSHBACK noted as design defense / style) -->

## Codex verdict

**ACCEPT** with 2 PUSHBACK items noted but not actioned in this commit:

1. **Newline-strip placement** (PUSHBACK → defend the design choice): codex
   flagged that newlines are stripped in the UI renderer (`displayArgs` in
   `ToolCallStatus`) rather than at TOOL_CALL_ARGS-append time in the
   reducer. The reducer's `argsBuffer` is intentionally **raw** so the
   eventual `JSON.parse` on TOOL_CALL_END sees an unmodified payload —
   stripping newlines in the reducer would corrupt valid JSON that
   contains newlines inside string values (e.g.
   `{"poem": "line1\nline2"}`). The UI-layer strip is a display-only
   concern (prevent vertical preview thrash mid-stream) and reverses
   automatically when `argsPretty` takes over on END.

2. **Commit subject 58 chars >50 limit** (PUSHBACK → noted, not amended):
   `feat(chat): stream TOOL_CALL_ARGS into collapsible preview` is 8
   chars over CLAUDE.md's ≤50 target. Per CLAUDE.md "prefer new commits
   over --amend", not amending; future G/Pillar commits target ≤50
   exact.

## Findings + responses

### 1. Cross-stack field consistency (ACCEPT)
All 3 stacks use identical `argsBuffer` + `argsPretty` field names.
No drift.

### 2. Multi-concurrent-tool-calls isolation (ACCEPT)
Each handler keys lookups by `toolCallId` / `id` before appending
delta. No cross-contamination risk.

### 3. Reducer purity (ACCEPT)
All 3 stacks create new objects via spread (`{...tc}`) or `copyWith()`
rather than mutating in place. Change detection intact.

### 4. JSON parse fallback (ACCEPT)
On `TOOL_CALL_END`, parse failure surfaces raw buffer (not empty
string). Contract test asserts the `catch + buffer` co-occurrence
pattern in each reducer.

### 5. Empty buffer handling (ACCEPT)
If no args streamed, `argsPretty` stays undefined (not `''`) so UI
`if (argsPretty)` cleanly hides the collapsible.

### 6. Wire schema isolation (ACCEPT)
`forge/templates/_shared/ui-protocol/tool_call_info.schema.json`
unchanged. Pydantic backend unchanged. New fields pure client-side.
Vue uses extends-by-shadowing pattern (`ToolCallInfo extends _WireToolCallInfo`),
Svelte + Flutter have hand-rolled `ToolCallInfo` already so add
directly.

### 7. Newline-strip placement (PUSHBACK → DEFENDED, no change)
See top section. The reducer is the wrong layer — strip-on-append
breaks valid JSON containing newlines inside string values.
UI-layer strip is the right scope.

### 8. Collapsible primitive per platform (ACCEPT)
`<details>` for Vue/Svelte, `ExpansionTile` for Flutter. Contract
test pins per-stack rather than insisting on a single widget.

### 9. argsBuffer lazy init (ACCEPT)
Preserves existing `expect(tc).toEqual({id, name, status: 'running'})`
assertions by leaving fields undefined until first delta.

### 10. UI gating + collapsible UX (ACCEPT)
Per-platform native (`<details>`, `ExpansionTile`). Tests pin behavior.

### 11. Test coverage (ACCEPT)
Vue 5 reducer + 3 UI + Svelte 6 + Flutter 4 + Python contract 21
assertions = 39 total. Covers accumulation, parse fallback, empty
buffer, concurrency.

### 12. Commit subject 58 chars (PUSHBACK → noted, not amended)
Per CLAUDE.md "prefer new commits over --amend". Lesson for next
G pillar commits.

## Convergence

12 findings — 10 ACCEPT, 2 PUSHBACK (1 defended as design, 1 noted as
style). No round 2 dispatched — the newline-strip design is correct;
the commit subject is style not correctness.

## Diff stat (unchanged)

```
15 files changed, 1052 insertions(+), 47 deletions(-)
```

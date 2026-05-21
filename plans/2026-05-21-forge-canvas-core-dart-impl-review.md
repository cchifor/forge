# Implementation review — feat/forge-canvas-core-dart-split — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 11 findings; 8 PASS, 1 PUSHBACK false-positive, 2 documented follow-ups; no round 2) -->

## Codex verdict

**Substantial correctness**, one claimed-Critical that's actually a **false positive**
(two distinct `ApprovalMode` types in different namespaces), one documented
follow-up (publish workflow), one acceptable alpha-stage tech-debt note (dio).

## Findings + responses

### 1. McpApprovalClient port fidelity (PASS)
Codex verified line-for-line parity with TS reference: cache key shape, TTL math
(3570s), auto-mode short-circuit, mint→invoke flow, 401 eviction + throw, baseUrl
trim, error message strings. 8 wire-protocol tests mirror the TS suite. **No action.**

### 2. ApprovalMode enum — claimed Critical "missing fromWire/wireValue" (PUSHBACK — FALSE POSITIVE)
**Codex's claim:** the Flutter template's `chat_providers.dart` uses
`ApprovalModeX.fromWire()` and `mode.wireValue`, but the new
`forge_canvas_core` enum only exposes `wireName`.

**Verification:** the Flutter template's `ApprovalMode` is a SEPARATE local
type defined at
`forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/chat_constants.dart:13`
with values `{defaultMode, bypass}` — an in-template chat-UI toggle for
"auto-approve all tool calls vs prompt every time". The `ApprovalModeX.fromWire`
+ `mode.wireValue` extension lives at `chat_constants.dart:15+` and operates on
the local enum.

The new `forge_canvas_core.ApprovalMode` is `{auto, promptOnce, promptEvery}`
— matches the **Python backend's** `approval_mode` wire field for MCP tool
calls (see `forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py`).
Different domain (template UX vs MCP wire protocol), different values,
different namespace.

The template imports `forge_canvas` aliased (`import 'package:forge_canvas/forge_canvas.dart' as fc;`)
so any `forge_canvas_core` symbol accessed through it appears as `fc.ApprovalMode`,
which does NOT collide with the unqualified `ApprovalMode` the template uses
for the local enum. The two coexist cleanly.

<!-- opus-pushback: Decline the proposed fix. Adding `fromWire`/`wireValue` to
`forge_canvas_core.ApprovalMode` solves a problem that doesn't exist — the
template uses its own enum, not this one. Phase 3 (template rewrite to consume
`forge_canvas_core` MCP types) will need to either rename one or namespace
imports, but that's a Phase 3 decision, not a Phase 2B requirement. -->

### 3. McpBridge stub (PASS)
Correct no-DOM shape; `mcpBridgeAvailable = false` matches TS pattern;
interface types reasonable; `TODO(phase-3)` honestly flags the absent
webview-backed implementation.

### 4. Re-export coverage (PASS)
`packages/forge-canvas-dart/lib/forge_canvas.dart` re-exports
`forge_canvas_core` symbols; covers what existing `chat_providers.dart`
imports via `fc.AgUiClient<AgUiEvent>`.

### 5. Pubspec / dio dependency (ACCEPT — alpha tech debt)
`dio` is pure-Dart (no Flutter runtime dep), so technically OK in a
no-Flutter package. Hard-dependency means future server-side / CLI
consumers must use dio. Document as post-1.0 tech debt: "consider
abstracting HTTP transport so consumers can bring their own client."

### 6. analysis_options.yaml lint preset switch (PASS)
Switch from `flutter_lints` → `lints/recommended.yaml` is correct for a
no-Flutter package.

### 7. Commit message (PASS)
`feat(dart): extract forge_canvas_core package` — 45 chars, within 50-char
limit per CLAUDE.md. Conventional Commits, no AI co-author trailer.

### 8. Dependency resolution at publish time (PARTIAL — documented follow-up)
**Issue 1**: missing `publish-pub-dev-core` workflow job. Documented in
README + PR description as required-before-first-prod-release follow-up.
Not a Phase 2B blocker.

**Issue 2**: `dependency_overrides` at publish — codex initially flagged
then verified it's a non-issue (pub.dev allows the field, it's simply
ignored by consumers). No action.

### 9. What did NOT move (PASS)
Verified: `agent_state_reducer.dart` + `ag_ui_event.dart` live in the
Flutter template, NOT in `forge-canvas-dart`. Phase 3 will extract them
into `forge_canvas_core`. Correct per plan.

### 10. dio vs http in AgUiClient (ACCEPT — alpha note)
Acceptable for alpha; flag as tech debt for 1.0 (abstract HTTP transport
via DI).

### 11. Plan compliance (PASS)
All Phase 2B deliverables shipped; Phase 3 honestly deferred.

## Convergence

11 findings — 8 PASS, 1 false-positive PUSHBACK with rationale, 2 documented
follow-ups (publish workflow + dio tech debt), 0 blockers. No round 2.

## Follow-ups (out of this PR's scope)

1. **Add `publish-pub-dev-core` job** to `.github/workflows/release.yml`
   mirroring the existing `publish-pub-dev` job for `forge_canvas`.
   Required before first production release tag.

2. **Phase 3 ApprovalMode disambiguation** (when the template rewrite lands):
   either rename the template's local `ApprovalMode` (e.g. to `AutoApprovalToggle`),
   or namespace-import the `forge_canvas_core` one (`import ... show ApprovalMode as McpApprovalMode`).

3. **Post-1.0 dio abstraction**: consider DI for HTTP transport in
   `forge_canvas_core` so non-dio consumers can plug in their own client.

## Diff stat

```
CHANGELOG.md                                                       |  38 +++
forge/codegen/event_union.py                                       |   5 +-
packages/forge-canvas-core-dart/CHANGELOG.md                       |  28 ++
packages/forge-canvas-core-dart/README.md                          | 136 +++++++++
packages/forge-canvas-core-dart/analysis_options.yaml              |  22 ++
packages/forge-canvas-core-dart/lib/forge_canvas_core.dart         |  25 ++
packages/forge-canvas-core-dart/lib/src/ag_ui_client.dart          |   0 (moved)
packages/forge-canvas-core-dart/lib/src/mcp_approval_client.dart   | 327 +++++
packages/forge-canvas-core-dart/lib/src/mcp_bridge.dart            | 137 +++++++++
packages/forge-canvas-core-dart/pubspec.yaml                       |  16 +
packages/forge-canvas-core-dart/test/mcp_approval_client_test.dart | 289 ++++++
packages/forge-canvas-dart/CHANGELOG.md                            |  39 +++
packages/forge-canvas-dart/lib/forge_canvas.dart                   |  17 +-
packages/forge-canvas-dart/pubspec.yaml                            |  11 +-
tests/test_event_union_codegen.py                                  |  10 +-
15 files changed, 1092 insertions(+), 8 deletions(-)
```

# forge_canvas_core

Framework-agnostic AG-UI runtime for forge canvas packages — Dart
sibling of the TypeScript `@forge/canvas-core`. Consumed by
`forge_canvas` (Flutter), which re-exports the full surface so existing
`package:forge_canvas/...` import sites stay stable.

**Status:** `1.0.0-alpha.1`. Pillar B Phase 2B of the forge architectural
improvement plan. Ships the SSE client, approval-aware MCP invoke
client, and MCP bridge interface types. The Flutter template rewrite
that consumes `forge_canvas_core` directly (deleting the in-template
duplicated reducer + events) is Pillar B Phase 3 — deferred until this
package actually publishes to pub.dev.

## What's in the package

- **`AgUiClient<E>`.** Pure-Dart SSE client (`dio` under the hood, no
  Flutter dep). Generic over the caller's typed event union via a
  `parser: (Map<String, dynamic>) -> E?` callback. Reconnect +
  `Last-Event-ID` resume are opt-in.
- **`McpApprovalClient`.** Calls `POST /mcp/approval/mint` before
  `POST /mcp/invoke` whenever `approvalMode != "auto"`. **This is the
  wire-protocol fix** for the historical 401 bug in non-`auto` MCP
  invocations (the Python router at
  `forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py`
  rejects invocations without a signed approval token). Mirrors the
  TS reference at `packages/canvas-core/src/mcp_approval_client.ts`
  line-for-line.
- **`McpBridge`** + **`mcpBridgeAvailable`**. Typed contract for the
  MCP iframe bridge so cross-stack expectations stay honest. The flag
  is `false` on Dart by design — Flutter has no `postMessage` /
  iframe model the way browsers do, and a real webview-backed
  bridge belongs in a separate package (out of scope here).

## Consumption

After publish, end users typically consume this transitively through
`forge_canvas`. Direct consumption is also supported:

```yaml
dependencies:
  forge_canvas_core: ^1.0.0-alpha.1
```

```dart
import 'package:forge_canvas_core/forge_canvas_core.dart';

final client = AgUiClient<AgUiEvent>(
  dio: Dio(),
  parser: AgUiEvent.parse,
);
final approver = McpApprovalClient();
final result = await approver.invoke(McpInvokeRequest(
  server: 'filesystem',
  tool: 'read_file',
  input: {'path': '/etc/hosts'},
  approvalMode: ApprovalMode.promptOnce,
));
```

## Publish checklist

Mirrors `RELEASING.md` (Python-side `forge` releases) and the pub.dev
publisher provisioning already done for `forge_canvas` per RFC-003.
`forge_canvas_core` reuses the same publisher (`forge-project.dev` per
RFC-003) and the same `PUB_DEV_CREDENTIALS` secret — no fresh ops
provisioning is required for this package.

### Pre-publish (one-time, ops setup)

Already done as part of `forge_canvas`'s RFC-003 publisher
provisioning. The same verified publisher covers both packages:

1. **pub.dev verified publisher** `forge-project.dev` exists.
2. **`PUB_DEV_CREDENTIALS` secret** is in the GitHub repo (gh secret).
3. **`.github/workflows/release.yml` already has a `publish-pub-dev`
   job** that publishes `forge_canvas`. Add a sibling
   `publish-pub-dev-core` job that publishes `forge_canvas_core` from
   `packages/forge-canvas-core-dart/` (follow-up PR — see "Open
   follow-ups" below).

### Per-release

1. **Bump version.** Edit `packages/forge-canvas-core-dart/pubspec.yaml`
   `version` field. Follow semver — alphas can break; betas are
   feature-frozen.
2. **Update CHANGELOG.** Note breaking changes, new exports,
   deprecations. Cross-link the PR(s) that landed each change.
3. **Run the package tests + analyze.** `dart pub get && dart analyze
   && dart test` from this directory. All three must pass.
4. **Tag.** `git tag forge_canvas_core-v1.0.0-alpha.1` (or whatever
   tag convention `release.yml` settles on) then `git push --tags`.
   The publish workflow handles the rest.
5. **Verify on pub.dev.** Browse to
   <https://pub.dev/packages/forge_canvas_core> after the workflow
   completes.
6. **Bump consumer `forge_canvas`** to match. Until both packages
   publish in lockstep, `forge_canvas`'s `pubspec.yaml` carries a
   `dependency_overrides` pointing at the on-disk
   `../forge-canvas-core-dart/` so local dev resolves without pub.dev.

### Versioning policy

- `forge_canvas_core` versions are independent of `forge_canvas`
  versions. `forge_canvas` tracks `forge_canvas_core` via a `^x.y.z`
  range and bumps on its own cadence.
- Pre-1.0 alphas can break. Post-1.0 follows semver strictly.
- TypeScript siblings (`@forge/canvas-core`, `@forge/canvas-vue`,
  `@forge/canvas-svelte`) have their own version stream — npm and
  pub.dev release cadences differ.

### Open follow-ups (tracked separately)

- Add `publish-pub-dev-core` job to
  `.github/workflows/release.yml` mirroring the existing
  `publish-pub-dev` job for `forge_canvas`.
- Update `.github/workflows/release-dryrun.yml` to run
  `flutter pub publish --dry-run` + `dart analyze` against
  `packages/forge-canvas-core-dart/` so the dry-run gates this
  package too.
- Phase 3: rewrite the Flutter chat template at
  `forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/`
  to import the reducer + event union from `forge_canvas_core`
  directly, deleting the in-template duplicates. Gated on this
  package actually publishing to pub.dev.

## Architecture cross-refs

- Pillar B Phase 1 (PR #68) — TypeScript `@forge/canvas-core` ships.
- Pillar B Phase 2A (PR #69) — `@forge/canvas-vue` /
  `@forge/canvas-svelte` re-export `@forge/canvas-core`.
- Pillar B Phase 2B (this PR) — Dart `forge_canvas_core` ships;
  `forge_canvas` re-exports.
- Pillar B Phase 3 (future) — Flutter chat template rewrites against
  `forge_canvas_core`; the 202-LOC reducer + event union in
  `flutter-frontend-template/.../chat/data/` collapses.

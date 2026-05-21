# @forge/canvas-core

Framework-agnostic AG-UI runtime for forge canvas packages. Consumed by
`@forge/canvas-vue`, `@forge/canvas-svelte`, and (mirrored) the Dart
`forge_canvas_core` package.

**Status:** `1.0.0-alpha.1`. Phase 1 of the architectural plan's Pillar B —
ships the reducer, SSE client, and MCP approval / iframe-bridge surface.
Phase 2 (npm publish + template rewrite to consume canvas-core directly)
is the work item this README's publish checklist enables.

## What's in the package

- **Pure AG-UI reducer.** `reduce(snapshot, event) -> snapshot`. Ported
  line-for-line from the Dart reference at
  `packages/forge-canvas-dart/lib/.../agent_state_reducer.dart` so the
  cross-stack contract is honest by construction.
- **`ChatStateSnapshot`** + helpers (`EMPTY_CHAT_SNAPSHOT`, `agentStateFromRaw`,
  `resetSnapshot`, `clearPendingPromptIfMatches`).
- **`AgUiClient<E>` — SSE.** `text/event-stream` parser with reconnect,
  exponential backoff, and `Last-Event-ID` resume. Mirrors the Dart
  reference; the WebSocket `AgUiClient` in canvas-vue / canvas-svelte
  is a different protocol for the `{kind, payload}` envelope.
- **`McpApprovalClient`.** Calls `/mcp/approval/mint` before
  `/mcp/invoke`, attaching the HMAC-signed token. **This is the
  wire-protocol fix** for the historical 401 bug in non-`auto` MCP
  invocations (see the Pillar B Phase 1 PR for context).
- **`McpBridge`.** Typed wrapper over
  `@modelcontextprotocol/ext-apps/app-bridge`. Web-only contract via
  `MCP_BRIDGE_AVAILABLE`.

## Consumption

After publish, consumers depend on this package transitively through
`@forge/canvas-vue` or `@forge/canvas-svelte` (which re-export the
full public surface under `SseAgUiClient`, `McpApprovalClient`, etc.).
Direct consumption is also supported:

```ts
import {
  reduce,
  AgUiClient,
  McpApprovalClient,
  EMPTY_CHAT_SNAPSHOT,
} from '@forge/canvas-core'
```

## Publish checklist

Mirrors `RELEASING.md` (Python-side `forge` releases) and the spirit
of RFC-003 for the Dart `forge_canvas` package. canvas-core is its
own npm-publish lane because the canvas packages release independently
of the Python CLI.

### Pre-publish (one-time, ops setup)

1. **Provision the `@forge` npm scope.**
   - Create the npm organization `forge` (or the actual scope name —
     verify by `npm org ls forge`).
   - Add the maintainer account with `publish` rights:
     `npm org set forge <maintainer> developer`.
   - Verify `npm whoami` returns the maintainer account locally and
     that `npm access list packages` shows the scope.

2. **Create an automation `NPM_TOKEN`.**
   - On npmjs.com → Account Settings → Access Tokens → Generate New Token
     → Granular access token with `Read and Publish` for the `@forge`
     scope. Set TTL to 365 days; rotate annually.
   - Add to the GitHub repo secrets as `NPM_TOKEN`
     (`gh secret set NPM_TOKEN --repo cchifor/forge`).

3. **Add the publish workflow.** Reuse the
   `.github/workflows/release.yml` shape — a `publish-canvas-core`
   job triggered on tag pushes matching `canvas-core-v*`:
   ```yaml
   publish-canvas-core:
     runs-on: ubuntu-latest
     if: startsWith(github.ref, 'refs/tags/canvas-core-v')
     steps:
       - uses: actions/checkout@v5
       - uses: actions/setup-node@v5
         with:
           node-version: '20'
           registry-url: 'https://registry.npmjs.org'
       - run: npm ci --workspace=@forge/canvas-core
       - run: npm test --workspace=@forge/canvas-core
       - run: npm run build --workspace=@forge/canvas-core
       - run: npm publish --workspace=@forge/canvas-core --access public
         env:
           NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
   ```

### Per-release

1. **Bump version.** Edit `packages/canvas-core/package.json` `version`
   field. Follow semver — alphas can break; betas are feature-frozen.
2. **Update CHANGELOG.** Note breaking changes, new exports, deprecations.
   Cross-link the PR(s) that landed each change.
3. **Run the workspace tests + build.** `npm test --workspace=@forge/canvas-core`
   then `npm run build --workspace=@forge/canvas-core`. Both must pass.
4. **Tag.** `git tag canvas-core-v1.0.0-alpha.1` then `git push --tags`.
   The publish workflow handles the rest.
5. **Verify on npm.** `npm view @forge/canvas-core@1.0.0-alpha.1`.
6. **Bump consumer canvas-vue + canvas-svelte** to match (their
   `package.json` `@forge/canvas-core` dep range). Open a follow-up
   PR for those bumps if the new version brings new exports or
   breaking changes.

### Versioning policy

- Canvas-core versions are independent of canvas-vue / canvas-svelte
  versions. The framework adapters track canvas-core via a `^x.y.z`
  range and bump on their own cadence.
- Pre-1.0 alphas can break. Post-1.0 follows semver strictly.
- The Dart sibling `forge_canvas_core` (when it exists) uses a
  separate version stream — Dart's pub.dev and npm have different
  release cadences and dependency models.

### Until canvas-core is published

`canvas-vue` and `canvas-svelte` declare `@forge/canvas-core@^1.0.0-alpha.1`
as a runtime dependency. The npm workspace at the repo root resolves
this via a symlink for local development. Until canvas-core publishes
to npm, end users installing `@forge/canvas-vue` or `@forge/canvas-svelte`
from npm will see an unresolvable dep. **Don't publish canvas-vue /
canvas-svelte before canvas-core lands.**

## Architecture cross-refs

- Phase 1 PR — the package itself + inline wire-bug fixes in templates.
- Phase 2 (in progress) — this README's publish checklist + canvas-vue /
  canvas-svelte re-exporting canvas-core's surface.
- Phase 3 (future) — template `useAgentClient.ts` / `agent-client.svelte.ts`
  rewrite (the 264→80 LOC collapse), gated on canvas-core actually
  publishing to npm.
- Phase 4 (future) — `forge_canvas_core` Dart split, mirrors Phase 3
  for the Flutter stack.

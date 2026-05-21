# Changelog

## 1.0.0-alpha.1 — unreleased

Initial extraction from `forge_canvas` (Pillar B Phase 2B of the forge
architectural improvement plan; sibling to the TypeScript
`@forge/canvas-core` package).

- **`AgUiClient<E>`** — pure-Dart AG-UI SSE client. Moved verbatim
  from `package:forge_canvas/src/ag_ui_client.dart` so behaviour is
  unchanged for downstream consumers. Reconnect + `Last-Event-ID`
  resume are opt-in via `reconnect: true`; default semantics match
  the deepagent one-shot stream.
- **`McpApprovalClient`** + **`McpApprovalRejected`** — new. Mirrors
  `@forge/canvas-core/src/mcp_approval_client.ts`. Calls
  `POST /mcp/approval/mint` before `POST /mcp/invoke` whenever the
  per-tool `approvalMode != "auto"`. Caches the signed token per
  `(server, tool, input)` triple for one hour (matching the
  backend's `MCP_APPROVAL_TOKEN_TTL_SECONDS` of 3600, trimmed by 30s
  for clock-drift safety). Surfaces 401 evictions as
  `McpApprovalRejected` so UI layers can prompt for re-approval
  rather than swallow a generic network error.
- **`McpBridge`** (interface types + `mcpBridgeAvailable = false`
  constant) — typed contract mirroring `@forge/canvas-core/src/mcp_bridge.ts`.
  Stubbed because Flutter has no DOM `postMessage` / iframe model;
  the constant lets Flutter `McpExtEngine` widgets short-circuit
  rather than throw. A real Flutter webview-backed implementation
  is out of scope for this package and tracked in Pillar F.

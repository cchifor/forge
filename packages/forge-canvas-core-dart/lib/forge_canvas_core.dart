/// `forge_canvas_core` — framework-agnostic AG-UI runtime.
///
/// Consumed by `forge_canvas` (Flutter), which re-exports the full
/// public surface so existing `package:forge_canvas/...` import sites
/// stay stable.
///
/// Sibling of the TypeScript `@forge/canvas-core` package. Pillar B
/// Phase 2B of the forge architectural improvement plan ships:
///
///   - Pure-Dart `AgUiClient<E>` (SSE + reconnect + Last-Event-ID).
///   - `McpApprovalClient` + `McpApprovalRejected` — the wire-protocol
///     bug fix for non-`auto` MCP tool invocations (mints an approval
///     token before invoking).
///   - Typed `McpBridge` contract (no-DOM stub on Dart by design —
///     `mcpBridgeAvailable` is `false`; a real Flutter webview-backed
///     implementation belongs in a separate package).
///
/// The per-stack Flutter template rewrite (Pillar B Phase 3) lands in
/// a follow-up PR; this package is the upstream dep that makes that
/// rewrite mechanical.
library forge_canvas_core;

export 'src/ag_ui_client.dart';
export 'src/mcp_approval_client.dart';
export 'src/mcp_bridge.dart';

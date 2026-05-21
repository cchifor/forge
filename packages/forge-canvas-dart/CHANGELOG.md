# Changelog

## 1.0.0-alpha.7 — unreleased

Pillar B Phase 2B of the forge architectural improvement plan. Splits
the framework-agnostic protocol surface out of `forge_canvas` into a
sibling pure-Dart package `forge_canvas_core` (mirroring the
TypeScript Phase 2A split: `@forge/canvas-core` ↔
`@forge/canvas-vue` / `@forge/canvas-svelte`).

**No breaking change is intended.** The public symbols the
`flutter-frontend-template` consumes (`AgUiClient<E>`) keep their
existing API; they're now re-exported from `forge_canvas_core` rather
than implemented directly inside this package.

- **Moved to `forge_canvas_core`:** `AgUiClient<E>` (was
  `lib/src/ag_ui_client.dart`). The implementation is byte-identical
  apart from the package boundary; consumers importing it via
  `package:forge_canvas/forge_canvas.dart` see no change.
- **New transitive surface via `forge_canvas_core`:**
  - `McpApprovalClient` + `McpApprovalRejected` — approval-aware MCP
    tool invocation. Mints a token via `POST /mcp/approval/mint`
    before calling `POST /mcp/invoke` whenever `approvalMode != "auto"`.
    Caches the signed token per `(server, tool, input)` for one hour
    (matching the backend's `MCP_APPROVAL_TOKEN_TTL_SECONDS`, trimmed
    by 30s for clock-drift safety). Surfaces 401 responses as
    `McpApprovalRejected` so UI layers can prompt for re-approval.
  - `McpBridge`, `McpBridgeHandlers`, `BridgeMessage`,
    `ToolCallRequest`, `OpenLinkRequest`, `IframeSizeChange`,
    `AppBridgeIdentity`, `AppBridgeCapabilities`, `AppBridgeContext`,
    and `mcpBridgeAvailable` (`false` on Dart) — typed contract
    mirroring the TS `@forge/canvas-core/src/mcp_bridge.ts` so
    cross-stack expectations stay honest by construction. The Dart
    side is a no-DOM stub because Flutter has no `postMessage` /
    iframe model.
- **`dependency_overrides`** points at the on-disk sibling
  `../forge-canvas-core-dart/` so local dev resolves without
  requiring `forge_canvas_core` to publish to pub.dev first.
  Stripped at publish time (pub.dev forbids `dependency_overrides`
  in published packages).

## 1.0.0-alpha.6 — unreleased

- **Breaking:** `AgUiClient` is now generic over event type `E` and takes a
  caller-supplied `parser: (Map<String, dynamic>) -> E?`. This lets
  generated apps keep their own typed `AgUiEvent` sealed-class hierarchy
  instead of the package's untyped value class. New `runAgent({threadId,
  runId, messages, state, forwardedProps, bearerToken})` helper matches
  the deepagent `POST /agent/run` contract directly. Reconnect +
  `Last-Event-ID` resume are now opt-in via `reconnect: true` (off by
  default to preserve the deepagent one-shot semantic). v2 Theme 9
  consolidated the deprecated Flutter-template-local `AgUiClient` into
  this package.
- **Breaking (canvas props):** Generated prop classes are now `final
  class` and lift nested-object array items into typed inner classes:
  `DataTableProps.columns` is `List<DataTableColumn>` (was
  `List<Map<String, dynamic>>`); `DynamicFormProps.fields` is
  `List<DynamicFormField>`; `WorkflowDiagramProps.nodes` /
  `.edges` are `List<WorkflowDiagramNode>` / `List<WorkflowDiagramEdge>`.
  Apps that constructed these props directly (or read `columns[i]` as
  a map) need to switch to the new typed shape — `*.fromJson(...)` /
  `.toJson()` still accept and emit the existing wire format, so
  payloads parsed off the agent stream are unaffected.
  `DataTableProps.rows` keeps `List<Map<String, dynamic>>` on purpose
  (its schema sets `additionalProperties: true`, no fixed shape).
  Inside `forge_canvas`, the `DataTable`, `DynamicForm`, and
  `WorkflowDiagram` widgets dropped their private `_Column`, `_Field`,
  `_WfNode`, and `_WfEdge` mirror classes; `CodeViewer.fromProps` /
  `Report.fromProps` now route through `CodeViewerProps.fromJson` /
  `ReportProps.fromJson` so the generated module is the single source
  of truth at parse time. The widgets' own constructors are unchanged.

## 1.0.0-alpha.1 — unreleased

- Initial scaffold. `CanvasRegistry`, `AgUiClient` with exponential-backoff
  reconnect + `Last-Event-ID` resume, `ForgeTheme` (shadcn-flavored
  Material 3). Real component extraction lands in `1.0.0-alpha.4`.

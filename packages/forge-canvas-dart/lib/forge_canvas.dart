/// Canvas registry + AG-UI SSE client + base components for
/// forge-generated Flutter applications.
library forge_canvas;

// Re-export the framework-agnostic protocol surface from
// `forge_canvas_core` (Pillar B Phase 2B). Existing consumers
// importing `package:forge_canvas/forge_canvas.dart` keep their
// `AgUiClient` / MCP types unchanged — the implementation simply
// moved into the sibling pure-Dart package.
//
// `forge_canvas_core` ships:
//   * `AgUiClient<E>` (SSE + reconnect + Last-Event-ID resume).
//   * `McpApprovalClient` + `McpApprovalRejected` + `McpInvokeRequest`
//     + `McpInvokeResult` + `ApprovalMode` (the wire-protocol bug
//     fix for non-`auto` MCP tool invocations).
//   * `McpBridge` interface types + `mcpBridgeAvailable` constant
//     (`false` on Dart — Flutter has no DOM iframe model; a real
//     webview-backed implementation belongs in a separate package).
export 'package:forge_canvas_core/forge_canvas_core.dart';

export 'src/canvas_registry.dart';
export 'src/lint.dart';
export 'src/theme.dart';

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
//
// Contract (Initiative #8): the generated library is the SINGLE
// source of truth for canvas-component prop shapes. The components
// under `src/components/` import the generated sealed classes
// directly (`DataTableColumn`, `DynamicFormField`,
// `WorkflowDiagramNode`, `WorkflowDiagramEdge`); the old
// hand-written private mirror classes (`_Column`, `_Field`,
// `_WfNode`, `_WfEdge`) are gone. To extend a prop schema, edit the
// JSON schema and run `python -m forge.codegen.canvas_props` — the
// components inherit the new typed shape automatically.
export 'src/generated/props.dart';

// Base components — all 5 canvas components now live in the package.
export 'src/components/report.dart';
export 'src/components/code_viewer.dart';
export 'src/components/data_table.dart';
export 'src/components/dynamic_form.dart';
export 'src/components/workflow_diagram.dart';

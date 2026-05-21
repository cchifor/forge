// @forge/canvas-vue — public entry point.
//
// Re-exports the canvas registry + AG-UI streaming client + base
// components. Typed against canvas.manifest.json (generated from
// forge/templates/_shared/canvas-components/*.props.schema.json).

export { createCanvasRegistry } from './canvas-registry'
export type {
  CanvasComponent,
  CanvasRegistry,
  CanvasResolution,
} from './canvas-registry'
export { lintProps, warnOnLintIssues } from './lint'
export type { LintIssue } from './lint'

// AG-UI WebSocket client — for AG-UI-compliant servers emitting the
// `{kind, payload}` envelope. Kept for backwards compatibility with
// existing consumers; the SSE-based client from @forge/canvas-core
// (re-exported below as `SseAgUiClient`) is the recommended choice
// for new code targeting agent-run protocols.
export { AgUiClient } from './ag_ui_client'
export type { AgUiClientOptions } from './ag_ui_client'

// @forge/canvas-core re-exports — Pillar B Phase 2 of the architectural
// improvement plan. Surface the framework-agnostic protocol package
// through canvas-vue so generated Vue projects pull canvas-core
// transitively and don't have to declare a direct dep. The future
// template rewrite imports the reducer + SSE client + McpApprovalClient
// from `@forge/canvas-vue` instead of going direct to canvas-core, so
// the import path stays inside the framework adapter even though the
// implementation lives in core.
//
// The SSE client is re-exported under `SseAgUiClient` to avoid the
// name clash with the WebSocket `AgUiClient` above — picking by
// transport is more honest than picking by package origin.
export {
  AgUiClient as SseAgUiClient,
  McpApprovalClient,
  McpApprovalRejected,
  createMcpBridge,
  MCP_BRIDGE_AVAILABLE,
  agentStateFromRaw,
  clearPendingPromptIfMatches,
  EMPTY_AGENT_STATE,
  EMPTY_CHAT_SNAPSHOT,
  parseEvent,
  reduce,
  resetSnapshot,
  splitOnFrameBoundary,
} from '@forge/canvas-core'
export type {
  AgUiClientOptions as SseAgUiClientOptions,
  AgUiEvent,
  AgUiRunPayload,
  AgentState,
  ApprovalMode,
  AppBridgeCapabilities,
  AppBridgeContext,
  AppBridgeIdentity,
  BridgeMessage,
  ChatMessage,
  ChatRole,
  ChatStateSnapshot,
  IframeSizeChange,
  McpApprovalClientOptions,
  McpBridge,
  McpBridgeHandlers,
  McpInvokeRequest,
  McpInvokeResult,
  OpenLinkRequest,
  ToolCallInfo,
  ToolCallRequest,
  ToolCallStatus,
  UpstreamAppBridge,
  UserPromptOption,
  UserPromptPayload,
  WorkspaceActivity,
} from '@forge/canvas-core'

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
//
// Contract (Initiative #8): the generated module is the SINGLE source
// of truth for canvas-component prop shapes. The per-component
// `<script setup>` blocks consume the generated interfaces directly
// (`defineProps<DynamicFormProps>()`); hand-written prop interface
// re-declarations inside component files are banned by convention. To
// extend a prop schema, edit the JSON schema and run
// `python -m forge.codegen.canvas_props` — the components inherit the
// new shape automatically.
export type {
  CodeViewerProps,
  DataTableProps,
  DynamicFormProps,
  ReportProps,
  WorkflowDiagramProps,
} from './generated/props'

// Base components — all 5 canvas components now live in the package.
export { default as Report } from './components/Report.vue'
export { default as CodeViewer } from './components/CodeViewer.vue'
export { default as DataTable } from './components/DataTable.vue'
export { default as DynamicForm } from './components/DynamicForm.vue'
export { default as WorkflowDiagram } from './components/WorkflowDiagram.vue'

// Error boundary — v2 Theme 8-C2. Wraps canvas-rendered subtrees so a
// crashing component does not cascade into the host app. Svelte/Dart
// counterparts are tracked for follow-up.
export { default as CanvasError } from './components/CanvasError.vue'

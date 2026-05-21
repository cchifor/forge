// @forge/canvas-svelte — public entry point.

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
// (re-exported via `./protocol` below as `SseAgUiClient`) is the
// recommended choice for new code targeting agent-run protocols.
//
// Exported here (not from `./protocol`) so the canvas-contract test
// at `tests/test_canvas_contract.py::test_svelte_shim_is_re_exported`
// — which greps this file for the literal `export { AgUiClient } from
// './ag_ui_client'` line — keeps passing.
export { AgUiClient } from './ag_ui_client'
export type { AgUiClientOptions } from './ag_ui_client'

// Framework-agnostic protocol surface (canvas-core re-exports —
// SseAgUiClient, McpApprovalClient, reducer, types). Lives in
// `./protocol` so tests can import a component-free slice; the full
// `@forge/canvas-svelte` surface from this file includes both
// protocol and Svelte components below.
export * from './protocol'

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
//
// Contract (Initiative #8): the generated module is the SINGLE source
// of truth for canvas-component prop shapes. The per-component
// `<script>` blocks consume the generated interfaces directly (e.g.
// `let props: DynamicFormProps = $props()`); hand-written prop
// interface re-declarations inside component files are banned by
// convention. To extend a prop schema, edit the JSON schema and run
// `python -m forge.codegen.canvas_props` — the components inherit the
// new shape automatically.
export type {
  CodeViewerProps,
  DataTableProps,
  DynamicFormProps,
  ReportProps,
  WorkflowDiagramProps,
} from './generated/props'

// Base components
export { default as Report } from './components/Report.svelte'
export { default as CodeViewer } from './components/CodeViewer.svelte'
export { default as DataTable } from './components/DataTable.svelte'
export { default as DynamicForm } from './components/DynamicForm.svelte'
export { default as WorkflowDiagram } from './components/WorkflowDiagram.svelte'

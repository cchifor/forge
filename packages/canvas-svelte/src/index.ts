// @forge/canvas-svelte — public entry point.

export { createCanvasRegistry } from './canvas-registry'
export type {
  CanvasComponent,
  CanvasRegistry,
  CanvasResolution,
} from './canvas-registry'
export { lintProps, warnOnLintIssues } from './lint'
export type { LintIssue } from './lint'

// AG-UI WebSocket client — mirrors `forge_canvas` (Dart). Single source
// of truth for inbound event decoding across Vue / Svelte / Flutter.
export { AgUiClient } from './ag_ui_client'
export type { AgUiClientOptions } from './ag_ui_client'

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
// The per-component `<script>` blocks still declare local Props
// interfaces; deletion in favour of these is deferred to Theme 1C
// once the codegen pipeline gates drift in CI.
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

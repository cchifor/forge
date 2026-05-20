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

// AG-UI WebSocket client — mirrors `forge_canvas` (Dart). Single source
// of truth for inbound event decoding across Vue / Svelte / Flutter.
export { AgUiClient } from './ag_ui_client'
export type { AgUiClientOptions } from './ag_ui_client'

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

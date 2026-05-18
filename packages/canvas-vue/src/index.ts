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

// Canvas component props — generated from
// forge/templates/_shared/canvas-components/*.props.schema.json.
// The per-component `<script setup>` blocks still declare local Props
// interfaces; deletion in favour of these is deferred to Theme 1C
// once the codegen pipeline gates drift in CI.
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

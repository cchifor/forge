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

// Base components — all 5 canvas components now live in the package.
export { default as Report } from './components/Report.vue'
export { default as CodeViewer } from './components/CodeViewer.vue'
export { default as DataTable } from './components/DataTable.vue'
export { default as DynamicForm } from './components/DynamicForm.vue'
export { default as WorkflowDiagram } from './components/WorkflowDiagram.vue'

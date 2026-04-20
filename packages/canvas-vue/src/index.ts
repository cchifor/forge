// @forge/canvas-vue — public entry point.
//
// Re-exports the canvas registry, AG-UI streaming client, and base
// components. Typed against canvas.manifest.json (generated from
// forge/templates/_shared/canvas-components/*.props.schema.json).
//
// Phase 3.1 scaffold: exports are placeholders until the extraction PR
// lifts the existing components out of the Vue template into this package.

export { createCanvasRegistry } from './canvas-registry'
export type {
  CanvasComponent,
  CanvasRegistry,
  CanvasResolution,
} from './canvas-registry'
export { lintProps, warnOnLintIssues } from './lint'
export type { LintIssue } from './lint'

// Base components — Report is the 1.0.0a4 extraction reference. The
// remaining components (CodeViewer, DataTable, DynamicForm,
// WorkflowDiagram) land in 1.0.0a5 following the same recipe:
//   1. Lift the .vue file from forge/templates/apps/vue-frontend-template
//   2. Replace inline dependencies with peer deps (marked, DOMPurify)
//   3. Wire into canvas.manifest.json via propsSchema
export { default as Report } from './components/Report.vue'
// export { default as CodeViewer } from './components/CodeViewer.vue'
// export { default as DataTable } from './components/DataTable.vue'
// export { default as DynamicForm } from './components/DynamicForm.vue'
// export { default as WorkflowDiagram } from './components/WorkflowDiagram.vue'

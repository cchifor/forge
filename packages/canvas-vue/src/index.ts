// @forge/canvas-vue — public entry point.
//
// Re-exports the canvas registry, AG-UI streaming client, and base
// components. Typed against canvas.manifest.json (generated from
// forge/templates/_shared/canvas-components/*.props.schema.json).
//
// Phase 3.1 scaffold: exports are placeholders until the extraction PR
// lifts the existing components out of the Vue template into this package.

export { createCanvasRegistry } from './canvas-registry'
export type { CanvasComponent, CanvasRegistry } from './canvas-registry'

// Base components (to be populated by extraction PR)
// export { default as CodeViewer } from './components/CodeViewer.vue'
// export { default as DataTable } from './components/DataTable.vue'
// export { default as DynamicForm } from './components/DynamicForm.vue'
// export { default as Report } from './components/Report.vue'
// export { default as WorkflowDiagram } from './components/WorkflowDiagram.vue'

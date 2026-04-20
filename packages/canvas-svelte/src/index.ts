// @forge/canvas-svelte — public entry point.

export { createCanvasRegistry } from './canvas-registry'
export type {
  CanvasComponent,
  CanvasRegistry,
  CanvasResolution,
} from './canvas-registry'
export { lintProps, warnOnLintIssues } from './lint'
export type { LintIssue } from './lint'

// Base components
export { default as Report } from './components/Report.svelte'
export { default as CodeViewer } from './components/CodeViewer.svelte'
export { default as DataTable } from './components/DataTable.svelte'
export { default as DynamicForm } from './components/DynamicForm.svelte'
export { default as WorkflowDiagram } from './components/WorkflowDiagram.svelte'

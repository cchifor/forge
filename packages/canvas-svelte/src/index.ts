// @forge/canvas-svelte — public entry point.

export { createCanvasRegistry } from './canvas-registry'
export type {
  CanvasComponent,
  CanvasRegistry,
  CanvasResolution,
} from './canvas-registry'
export { lintProps, warnOnLintIssues } from './lint'
export type { LintIssue } from './lint'

// Framework-agnostic protocol surface — re-exported through the
// `protocol` sub-module so tests + bundlers that don't need the Svelte
// component graph can import a lighter slice. The full
// `@forge/canvas-svelte` surface includes both the protocol and the
// components below.
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

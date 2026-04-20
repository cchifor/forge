// @forge/canvas-svelte — public entry point.
//
// Phase 3.1 scaffold. Matches @forge/canvas-vue's surface with Svelte 5
// runes internals. The extraction PR will lift existing components out
// of the svelte-frontend-template into this package.

export { createCanvasRegistry } from './canvas-registry'
export type {
  CanvasComponent,
  CanvasRegistry,
  CanvasResolution,
} from './canvas-registry'
export { lintProps, warnOnLintIssues } from './lint'
export type { LintIssue } from './lint'

// Base components — Report is the 1.0.0a4 extraction reference.
export { default as Report } from './components/Report.svelte'

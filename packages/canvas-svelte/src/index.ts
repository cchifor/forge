// @forge/canvas-svelte — public entry point.
//
// Phase 3.1 scaffold. Matches @forge/canvas-vue's surface with Svelte 5
// runes internals. The extraction PR will lift existing components out
// of the svelte-frontend-template into this package.

export { createCanvasRegistry } from './canvas-registry'
export type { CanvasComponent, CanvasRegistry } from './canvas-registry'

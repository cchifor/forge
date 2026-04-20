# @forge/canvas-vue

Canvas registry + AG-UI streaming client for forge-generated Vue 3 applications.

**Status:** `1.0.0-alpha.1` scaffold. Phase 3.1 of the forge 1.0 roadmap. The package
directory ships the layout, package.json, and entry-point stubs; the first publishable
build lands with `forge 1.0.0a4` once the source has been extracted from the Vue template.

## What it will export

```ts
import {
  CanvasRegistry,
  createCanvasRegistry,
  AgUiAgent,
  // Base components
  CodeViewer,
  DataTable,
  DynamicForm,
  Report,
  WorkflowDiagram,
} from '@forge/canvas-vue'
```

## Roadmap

- `1.0.0-alpha.1` (this) — scaffold
- `1.0.0-alpha.2` — extracted source, types from canvas-manifest.json
- `1.0.0-beta.1`  — production-ready public API
- `1.0.0`         — GA

## Architecture

See `docs/rfcs/RFC-004-canvas-packages.md` in the forge repo (pending).

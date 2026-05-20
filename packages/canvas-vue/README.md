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

## Prop-shape contract

The interfaces under `src/generated/props.ts` are the **single source
of truth** for canvas-component prop shapes. They are emitted from
`forge/templates/_shared/canvas-components/*.props.schema.json` by
`python -m forge.codegen.canvas_props`.

Rules:

- The package's public surface re-exports only the generated
  interfaces (`CodeViewerProps`, `DataTableProps`, `DynamicFormProps`,
  `ReportProps`, `WorkflowDiagramProps`).
- The per-component `<script setup>` blocks call
  `defineProps<TheGeneratedInterface>()` directly. Hand-written
  re-declarations of schema-driven prop shapes — local
  `interface Field { ... }`, `interface Column { ... }`,
  `interface Node { ... }`, `interface Edge { ... }` — are
  **banned**: the codegen pipeline tests grep for them and will fail
  CI. Vue exposes component-emitted concerns via `defineEmits<>()`
  rather than the props block, so it does not need a `Props extends`
  carve-out.
- To extend a prop schema, edit the JSON schema and re-run the
  codegen — components inherit the new shape automatically. Drop the
  shipped TS/Dart files into the same regeneration run so the three
  runtimes stay aligned.

## Architecture

See `docs/rfcs/RFC-004-canvas-packages.md` in the forge repo (pending).

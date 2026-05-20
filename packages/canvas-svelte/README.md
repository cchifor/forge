# @forge/canvas-svelte

Canvas registry + AG-UI streaming client for forge-generated Svelte 5 applications.

**Status:** `1.0.0-alpha.1` scaffold. Phase 3.1 of the forge 1.0 roadmap.

## What this package provides

- `createCanvasRegistry(initial?)` — registry for mapping `component_name` → Svelte 5 component
- Upcoming: base components (`CodeViewer`, `DataTable`, etc.) + `AgUiAgent` Svelte wrapper

## Installing

```bash
npm install @forge/canvas-svelte @ag-ui/client
```

## Usage

```ts
import { createCanvasRegistry } from '@forge/canvas-svelte'

const registry = createCanvasRegistry()
registry.register({
  name: 'DataTable',
  component: MyDataTable,
})
```

## Roadmap

- `1.0.0-alpha.1` (this) — scaffold
- `1.0.0-alpha.4` — extracted Svelte components with typed props
- `1.0.0` — GA

## Prop-shape contract

The interfaces under `src/generated/props.ts` are the **single source
of truth** for canvas-component prop shapes. They are emitted from
`forge/templates/_shared/canvas-components/*.props.schema.json` by
`python -m forge.codegen.canvas_props`.

Rules:

- The package's public surface re-exports only the generated
  interfaces (`CodeViewerProps`, `DataTableProps`, `DynamicFormProps`,
  `ReportProps`, `WorkflowDiagramProps`).
- The per-component `<script>` blocks consume the generated
  interfaces directly (e.g.
  `let props: DynamicFormProps = $props()`). Hand-written
  re-declarations of schema-driven prop shapes — local
  `interface Field { ... }`, `interface Column { ... }`,
  `interface Node { ... }`, `interface Edge { ... }` — are
  **banned**: the codegen pipeline tests grep for them and will fail
  CI.
- A local `interface Props extends GeneratedProps { ... }` is
  **allowed** when a Svelte 5 component needs to layer non-schema
  props on top (for example, event-callback props such as `onsubmit`
  / `oncancel` that the agent never sends but Svelte's `$props()`
  reads from the parent). The schema-driven fields must come from
  the generated interface; only purely component-emitted concerns
  are added on top.
- To extend a prop schema, edit the JSON schema and re-run the
  codegen — components inherit the new shape automatically.

See the [forge repository](https://github.com/forge-project/forge) for the 1.0 roadmap.

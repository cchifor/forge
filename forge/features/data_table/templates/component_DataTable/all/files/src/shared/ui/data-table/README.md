# DataTable — Layer-1 component

A TanStack-Table-backed data grid for the generated Vue app. Pure UI: no
backend, store, or domain coupling. Opt-in via `components=["DataTable"]` in
the forge `ProjectConfig` — absent from every golden preset by default.

## What ships

Everything lands under `src/shared/ui/data-table/`:

- **`DataTable.vue`** — the grid surface (sticky header, pinned columns,
  responsive width tiers via `useContainerSize`, sort chips, selection).
- **`ColumnManagerMenu.vue`** — popover exposing per-column visibility
  (checkbox), reorder (native HTML5 drag-and-drop, no extra npm dep), and
  pin-to-left toggles.
- **`SortChip.vue`** — the sort-direction chip used in headers.
- **`useDataTable.ts`** — the facade composable wiring TanStack's
  `useVueTable` to the column manager + canonical select column.
- **`useColumnManager.ts`** + sub-composables `useColumnVisibility`,
  `useColumnOrder`, `useColumnPinning`, `useColumnSizing` — the
  localStorage-persisted column-state engine.
- **`augmentedColumns.ts`**, **`breakpoints.ts`**, **`types.ts`** — helpers
  and the public type surface.
- **`checkbox/`** and **`popover/`** — self-contained radix-vue primitive
  wrappers, kept local so this feature collides with nothing else in
  `@/shared/ui/`. (The NotificationCenter feature ships its own
  `@/shared/ui/popover`; this one never touches it.)
- Co-located **`*.test.ts`** files run in the generated project's vitest CI.

## Public API (from `index.ts`)

```ts
import {
  DataTable,
  ColumnManagerMenu,
  useDataTable,
  twBelow,
  type PinSide,
  useColumnManager,
  type ColumnManager,
  type ColumnManagerItem,
  type UseColumnManagerOptions,
  useColumnVisibility,
  type ColumnVisibility,
  useColumnOrder,
  type ColumnOrder,
  useColumnPinning,
  type ColumnPinning,
  useColumnSizing,
  type ColumnSizing,
  DATA_TABLE_LAYOUT,
  type DataTableColumnDef,
  type DataTableColumnMeta,
  type DataTableLayout,
  type DataTableMode,
} from '@/shared/ui/data-table'
```

## Wiring

`.vue` components can't be auto-wired into your app, so import what you need
yourself:

```ts
import { DataTable, ColumnManagerMenu, useDataTable } from '@/shared/ui/data-table'
```

Pass your column defs + rows into `useDataTable`, render `<DataTable>` with the
returned `table`, and drop `<ColumnManagerMenu>` into a filter bar wired to the
same `manager` so the menu and grid share one source of truth.

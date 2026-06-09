import {
  computed,
  h,
  ref,
  toValue,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue'
import { refDebounced } from '@vueuse/core'
import {
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useVueTable,
  type ColumnDef,
  type FilterFn,
  type RowSelectionState,
  type SortingState,
} from '@tanstack/vue-table'
import { Checkbox } from './checkbox'
import { useBreakpoint } from '@/shared/composables/useBreakpoint'
import type { DataTableColumnDef } from './types'
import {
  useColumnManager,
  twBelow,
  type ColumnManager,
  type PinSide,
} from './useColumnManager'

export { twBelow }
export type { PinSide, ColumnManager }

export interface UseDataTableInputs<T> {
  /** Column defs (ref / getter / plain). Supports TanStack `ColumnDef` + `meta`. */
  columns: MaybeRefOrGetter<DataTableColumnDef<T>[]>
  /** Row data. */
  rows: MaybeRefOrGetter<T[]>
  /** Required stable id — used as the localStorage key for user preferences. */
  tableId: string
  /**
   * When supplied, the table reads its column-management state from this
   * hoisted manager. The page typically passes the same manager into the
   * FilterBar's `<ColumnManagerMenu>`, so the menu and table share one
   * source of truth. When omitted, `useDataTable` instantiates a manager
   * internally — preserving back-compat for any caller that uses
   * `<DataTable>` standalone.
   */
  manager?: ColumnManager
  /** Row selection state (two-way). */
  selection?: Ref<RowSelectionState>
  onSelectionChange?: (next: RowSelectionState) => void
  /** Derive a stable row id — defaults to `row.id` if present. */
  getRowId?: (row: T) => string
  /** Debounced global filter. */
  globalFilter?: Ref<string | undefined>
  initialSorting?: SortingState
  /**
   * Ignored when `manager` is supplied — the manager's `enableRowSelection`
   * is the single source of truth so the table never disagrees with the
   * column manager about whether the select column exists. Used as a
   * default only when instantiating a manager internally.
   */
  enableRowSelection?: boolean
  globalFilterFn?: FilterFn<T>
  /** Page size for `mode: 'pagination'`. Ignored otherwise. */
  pageSize?: number
}

/**
 * Canonical selection column definition. Substituted in for the synthetic
 * descriptor that `useColumnManager` emits when `enableRowSelection: true`
 * — defined here (not in the manager) so the manager stays a pure state
 * composable with no Vue render concerns.
 *
 * Header semantics: `getIsAllPageRowsSelected` / `toggleAllPageRowsSelected`
 * — toggles the rows currently in the row model after filtering. In
 * `mode: 'infinite'` that's the entire (filtered) loaded set; in
 * `mode: 'pagination'` it's the current page. Matches the user's "all
 * visible rows" requirement in both modes.
 */
const CANONICAL_SELECT_COLUMN = {
  id: 'select',
  // 32 px matches the original `useDataSourcesTable` select column. TanStack
  // uses `column.size` for sticky-left offset math (`column.getStart('left')`
  // for downstream pinned columns); the rendered TH width is forced to 40 px
  // by the `w-10` Tailwind class in DataTable.vue. Without `size`, TanStack
  // defaults to 150 px and the next pinned column's `left:` style would jump
  // ahead of the actual rendered checkbox cell, leaving a ~110 px gap.
  size: 32,
  enableSorting: false,
  enableResizing: false,
  enablePinning: false,
  meta: {
    alwaysVisible: true,
    enableResizing: false,
    enablePinning: false,
  },
  header: ({ table }) =>
    h(Checkbox, {
      checked: table.getIsAllPageRowsSelected()
        ? true
        : table.getIsSomePageRowsSelected()
          ? 'indeterminate'
          : false,
      'onUpdate:checked': (v: boolean) => table.toggleAllPageRowsSelected(!!v),
      'aria-label': 'Select all',
    }),
  cell: ({ row }) =>
    h(Checkbox, {
      checked: row.getIsSelected(),
      'onUpdate:checked': (v: boolean) => row.toggleSelected(!!v),
      'aria-label': 'Select row',
    }),
} as unknown as ColumnDef<unknown, unknown>

export function useDataTable<T>(inputs: UseDataTableInputs<T>) {
  // Capture the breakpoint reactive once at setup so the
  // onColumnVisibilityChange handler can read it without re-instantiating
  // the composable on every TanStack-driven update.
  const { tw } = useBreakpoint()

  const rowsGetter = () => toValue(inputs.rows)

  const sorting = ref<SortingState>(inputs.initialSorting ?? [])

  const rawGlobalFilter = computed({
    get: () => inputs.globalFilter?.value ?? '',
    set: (v) => {
      if (inputs.globalFilter) inputs.globalFilter.value = v
    },
  })
  const debouncedGlobalFilter = refDebounced(rawGlobalFilter, 180)

  const manager: ColumnManager =
    inputs.manager ??
    useColumnManager<T>(inputs.tableId, inputs.columns, {
      enableRowSelection: inputs.enableRowSelection ?? true,
    })

  const enableRowSelection = manager.enableRowSelection

  // Substitute the canonical select renderer for the manager's synthetic
  // descriptor (id: 'select' with no header). Caller-supplied 'select'
  // columns already carry header/cell and pass through unchanged.
  const finalColumns = computed<ColumnDef<T, unknown>[]>(() =>
    manager.augmentedColumns.value.map((c) => {
      const id = (c.id ??
        (c as { accessorKey?: string }).accessorKey) as string
      if (id === 'select' && !c.header) {
        return CANONICAL_SELECT_COLUMN as ColumnDef<T, unknown>
      }
      return c as ColumnDef<T, unknown>
    }),
  )

  const table = useVueTable<T>({
    get data() {
      return rowsGetter()
    },
    get columns() {
      return finalColumns.value
    },
    getRowId: (row) =>
      inputs.getRowId
        ? inputs.getRowId(row)
        : ((row as unknown as { id?: string }).id ?? ''),
    state: {
      get sorting() {
        return sorting.value
      },
      get globalFilter() {
        return debouncedGlobalFilter.value
      },
      get rowSelection(): RowSelectionState {
        return inputs.selection?.value ?? {}
      },
      get columnVisibility() {
        return manager.columnVisibility.value
      },
      get columnOrder() {
        return manager.columnOrder.value
      },
      get columnSizing() {
        return manager.columnSizing.value
      },
      get columnPinning() {
        return manager.columnPinning.value
      },
    },
    enableRowSelection,
    enableColumnResizing: true,
    enablePinning: true,
    columnResizeMode: 'onEnd',
    onSortingChange: (updater) => {
      sorting.value =
        typeof updater === 'function' ? updater(sorting.value) : updater
    },
    onGlobalFilterChange: (updater) => {
      const next =
        typeof updater === 'function'
          ? updater(rawGlobalFilter.value)
          : updater
      rawGlobalFilter.value = next
    },
    onRowSelectionChange: (updater) => {
      if (!inputs.selection) return
      const next =
        typeof updater === 'function'
          ? updater(inputs.selection.value)
          : updater
      inputs.selection.value = next
      inputs.onSelectionChange?.(next)
    },
    onColumnVisibilityChange: (updater) => {
      const current = manager.columnVisibility.value
      const next = typeof updater === 'function' ? updater(current) : updater
      // Write only diffs from the breakpoint-derived base; the manager owns
      // the merge logic when it reads.
      const overrides = { ...manager.userVisibility.value }
      for (const col of manager.augmentedColumns.value) {
        const id = (col.id ??
          (col as { accessorKey?: string }).accessorKey) as string
        if (!id) continue
        const baselineVisible = next[id] !== false
        const hintHides =
          col.meta?.responsiveHidden &&
          twBelow(tw.value, col.meta.responsiveHidden.below)
        const baseWithoutOverride = !hintHides
        if (baselineVisible === baseWithoutOverride) delete overrides[id]
        else overrides[id] = baselineVisible
      }
      manager.userVisibility.value = overrides
    },
    onColumnOrderChange: (updater) => {
      const next =
        typeof updater === 'function'
          ? updater(manager.columnOrder.value)
          : updater
      manager.setColumnOrder([...next])
    },
    onColumnSizingChange: (updater) => {
      const next =
        typeof updater === 'function'
          ? updater(manager.columnSizing.value)
          : updater
      manager.setColumnSizing({ ...next })
    },
    onColumnPinningChange: (updater) => {
      const next =
        typeof updater === 'function'
          ? updater(manager.columnPinning.value)
          : updater
      // Right pinning was removed end-to-end; persist only `left`.
      manager.userPinning.value = {
        left: [...(next.left ?? [])],
        right: [],
      }
    },
    globalFilterFn: inputs.globalFilterFn,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: inputs.pageSize
      ? getPaginationRowModel()
      : undefined,
    initialState: inputs.pageSize
      ? { pagination: { pageIndex: 0, pageSize: inputs.pageSize } }
      : undefined,
  })

  const hasNoMatches = computed(
    () => rowsGetter().length > 0 && table.getRowModel().rows.length === 0,
  )

  return {
    table,
    manager,
    // Re-expose manager surface so DataTable.vue / RecordsTable.vue can
    // pipe it without reaching into `manager.*` directly.
    togglableColumns: manager.togglableColumns,
    columnVisibility: manager.columnVisibility,
    columnOrder: manager.columnOrder,
    columnSizing: manager.columnSizing,
    columnPinning: manager.columnPinning,
    userVisibility: manager.userVisibility,
    userOrder: manager.userOrder,
    userSizing: manager.userSizing,
    userPinning: manager.userPinning,
    hasOverrides: manager.hasOverrides,
    toggleColumn: manager.toggleColumn,
    setColumnOrder: manager.setColumnOrder,
    setColumnSizing: manager.setColumnSizing,
    togglePinColumn: manager.togglePinColumn,
    resetAll: manager.resetAll,
    // Legacy alias retained for DataTable.test.ts tests.
    resetColumnVisibility: () => {
      manager.userVisibility.value = {}
    },
    hasNoMatches,
  }
}

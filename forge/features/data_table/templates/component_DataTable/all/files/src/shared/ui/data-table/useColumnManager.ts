import {
  computed,
  ref,
  type ComputedRef,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue'
import type {
  ColumnOrderState,
  ColumnPinningState,
  VisibilityState,
} from '@tanstack/vue-table'
import type { DataTableColumnDef } from './types'
import { useAugmentedColumns } from './augmentedColumns'
import { useColumnVisibility } from './useColumnVisibility'
import { useColumnOrder } from './useColumnOrder'
import { useColumnPinning, type PinSide } from './useColumnPinning'
import { useColumnSizing } from './useColumnSizing'
import { twBelow } from './breakpoints'

export { twBelow }
export type { PinSide }

export interface ColumnManagerItem {
  id: string
  label: string
  canResize: boolean
  canPin: boolean
}

export interface UseColumnManagerOptions {
  /**
   * When true, the manager prepends a synthetic ``'select'`` descriptor
   * to the column set used for ``togglableColumns``, ``columnOrder``,
   * and ``columnPinning`` derivation. ``<DataTable>`` reads
   * ``enableRowSelection`` off the returned manager and substitutes the
   * actual checkbox renderers for the synthetic entry before handing
   * columns to TanStack — so the page-level manager and the table
   * never disagree about whether the select column exists.
   *
   * Defensive: if the user-supplied columns already include one with
   * ``id === 'select'``, no synthesis happens — the caller's column wins.
   */
  enableRowSelection?: boolean
}

/**
 * Public manager handle. Backwards-compatible facade composed from
 * four single-responsibility sub-composables (visibility, order,
 * pinning, sizing). Each slice owns its own persistence key and is
 * importable directly for callers that only need one concern.
 */
export interface ColumnManager {
  togglableColumns: ComputedRef<ColumnManagerItem[]>
  augmentedColumns: ComputedRef<DataTableColumnDef<unknown>[]>
  columnVisibility: ComputedRef<VisibilityState>
  columnOrder: ComputedRef<ColumnOrderState>
  columnSizing: ComputedRef<Record<string, number>>
  columnPinning: ComputedRef<ColumnPinningState>
  userVisibility: Ref<Record<string, boolean>>
  /**
   * Form-binding state — defaults all-true for every togglable column
   * regardless of the runtime layout, reflecting only user toggles.
   * The popover's checkboxes bind to this so the auto-hide from
   * ``responsiveHidden`` stays invisible to the form. See
   * ``useColumnVisibility`` for the three-state semantics.
   */
  userVisibilityIntent: ComputedRef<Record<string, boolean>>
  userOrder: Ref<ColumnOrderState>
  userSizing: Ref<Record<string, number>>
  userPinning: Ref<ColumnPinningState>
  hasOverrides: ComputedRef<boolean>
  /**
   * ``true`` iff the user has explicitly hidden at least one column.
   * Drives the column-manager trigger-button "filtering active" dot.
   * Reorder and pin are user customisations, not "filtering" — they
   * do not light this flag.
   */
  hasUserHiddenColumns: ComputedRef<boolean>
  enableRowSelection: boolean
  toggleColumn: (id: string, visible: boolean) => void
  setColumnOrder: (ids: string[]) => void
  setColumnSizing: (next: Record<string, number>) => void
  togglePinColumn: (id: string, side: PinSide) => void
  setContainerWidth: (w: number) => void
  resetAll: () => void
}

interface DevRegistry {
  seen: Set<string>
}
const isTestEnv =
  import.meta.env.MODE === 'test' || import.meta.env.VITEST === 'true'
const devRegistry: DevRegistry | null =
  import.meta.env.DEV && !isTestEnv ? { seen: new Set() } : null

function warnDuplicateTableId(id: string) {
  if (!devRegistry) return
  if (devRegistry.seen.has(id)) {
    console.warn(
      `[DataTable] Duplicate tableId "${id}" — two managers share localStorage state.`,
    )
  } else {
    devRegistry.seen.add(id)
  }
}

/**
 * Per-tenant per-browser column preferences, keyed by ``tableId``.
 * Hoisted to the page level (the page passes the returned handle into
 * both ``<ColumnManagerMenu>`` for the FilterBar UI and ``<DataTable>``
 * via its ``manager`` prop), so a single instance owns all derived
 * state. Falls back to internal instantiation when ``<DataTable>`` is
 * used standalone.
 *
 * Composed from four single-responsibility sub-composables —
 * ``useColumnVisibility``, ``useColumnOrder``, ``useColumnPinning``,
 * ``useColumnSizing``. Each can be imported directly when a future
 * caller only needs one slice (e.g., a stand-alone "column visibility
 * picker" component without order or pinning concerns).
 */
export function useColumnManager<T>(
  tableId: string,
  columns: MaybeRefOrGetter<DataTableColumnDef<T>[]>,
  options: UseColumnManagerOptions = {},
): ColumnManager {
  warnDuplicateTableId(tableId)

  const enableRowSelection = options.enableRowSelection ?? false
  const containerWidth = ref(0)

  const augmentedColumns = useAugmentedColumns(columns, enableRowSelection)

  const visibility = useColumnVisibility(tableId, augmentedColumns, {
    containerWidth,
  })
  const order = useColumnOrder(tableId, augmentedColumns)
  const pinning = useColumnPinning(tableId, augmentedColumns)
  const sizing = useColumnSizing(tableId)

  const togglableColumns = computed<ColumnManagerItem[]>(() =>
    augmentedColumns.value
      .filter((c) => !c.meta?.alwaysVisible)
      .map((c) => ({
        id: (c.id ?? (c as { accessorKey?: string }).accessorKey) as string,
        label:
          c.meta?.cardLabel ??
          (typeof c.header === 'string' ? c.header : (c.id ?? '')),
        canResize: c.meta?.enableResizing !== false,
        canPin: c.meta?.enablePinning !== false,
      }))
      .filter((c) => !!c.id),
  )

  const hasOverrides = computed(
    () =>
      visibility.hasOverrides.value ||
      order.hasOverrides.value ||
      pinning.hasOverrides.value ||
      sizing.hasOverrides.value,
  )

  function setContainerWidth(w: number) {
    containerWidth.value = w
  }

  function resetAll() {
    visibility.reset()
    order.reset()
    pinning.reset()
    sizing.reset()
  }

  return {
    togglableColumns,
    augmentedColumns,
    columnVisibility: visibility.columnVisibility,
    columnOrder: order.columnOrder,
    columnSizing: sizing.columnSizing,
    columnPinning: pinning.columnPinning,
    userVisibility: visibility.userVisibility,
    userVisibilityIntent: visibility.userVisibilityIntent,
    userOrder: order.userOrder,
    userSizing: sizing.userSizing,
    userPinning: pinning.userPinning,
    hasOverrides,
    hasUserHiddenColumns: visibility.hasUserHiddenColumns,
    enableRowSelection,
    toggleColumn: visibility.toggleColumn,
    setColumnOrder: order.setColumnOrder,
    setColumnSizing: sizing.setColumnSizing,
    togglePinColumn: pinning.togglePinColumn,
    setContainerWidth,
    resetAll,
  }
}

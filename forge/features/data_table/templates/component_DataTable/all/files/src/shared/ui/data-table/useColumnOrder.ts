import {
  computed,
  toValue,
  type ComputedRef,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue'
import { useStorage } from '@vueuse/core'
import type { ColumnOrderState } from '@tanstack/vue-table'
import type { DataTableColumnDef } from './types'

export interface ColumnOrder {
  userOrder: Ref<ColumnOrderState>
  columnOrder: ComputedRef<ColumnOrderState>
  hasOverrides: ComputedRef<boolean>
  setColumnOrder: (ids: string[]) => void
  reset: () => void
}

/**
 * Per-tenant per-browser column order, keyed by ``tableId``. Sliced
 * out of ``useColumnManager`` so each column concern lives in its own
 * single-responsibility composable behind a unified facade.
 *
 * ``alwaysVisible`` columns lock at their declared positions
 * regardless of ``userOrder`` — the column-manager menu hides them
 * (selection checkbox, row actions, the ``cardSubtitle`` column), so
 * the persisted ``userOrder`` never references those IDs. Without this
 * lock, reordering any togglable column would silently move the
 * selection checkbox to the tail (PR #88 regression, pinned by tests).
 */
export function useColumnOrder<T>(
  tableId: string,
  augmentedColumns: MaybeRefOrGetter<DataTableColumnDef<T>[]>,
): ColumnOrder {
  const userOrder = useStorage<ColumnOrderState>(
    `dt:${tableId}:order`,
    [],
    undefined,
    { mergeDefaults: true },
  )

  const columnOrder = computed<ColumnOrderState>(() => {
    const cols = toValue(augmentedColumns) as DataTableColumnDef<unknown>[]
    const declared = cols
      .map((c) => (c.id ?? (c as { accessorKey?: string }).accessorKey) as string)
      .filter(Boolean)
    if (userOrder.value.length === 0) return declared

    const alwaysVisibleIds = new Set(
      cols
        .filter((c) => c.meta?.alwaysVisible)
        .map(
          (c) =>
            (c.id ?? (c as { accessorKey?: string }).accessorKey) as string,
        )
        .filter(Boolean),
    )
    const inUser = new Set(userOrder.value)
    const orderedTogglable = [
      ...userOrder.value.filter(
        (id) => declared.includes(id) && !alwaysVisibleIds.has(id),
      ),
      ...declared.filter(
        (id) => !inUser.has(id) && !alwaysVisibleIds.has(id),
      ),
    ]
    const togglableQueue = [...orderedTogglable]
    return declared.map((id) =>
      alwaysVisibleIds.has(id) ? id : (togglableQueue.shift() ?? id),
    )
  })

  const hasOverrides = computed(() => userOrder.value.length > 0)

  function setColumnOrder(ids: string[]) {
    userOrder.value = [...ids]
  }

  function reset() {
    userOrder.value = []
  }

  return {
    userOrder,
    columnOrder,
    hasOverrides,
    setColumnOrder,
    reset,
  }
}

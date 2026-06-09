import {
  computed,
  toValue,
  type ComputedRef,
  type MaybeRefOrGetter,
} from 'vue'
import type { DataTableColumnDef } from './types'

/**
 * Synthetic ``select`` column descriptor — no header, no cell renderer.
 * ``<DataTable>`` (via ``useDataTable``) substitutes the canonical
 * checkbox renderer before handing columns to TanStack. Defining it
 * here keeps ``useColumnManager`` and its sub-composables free of Vue
 * render concerns.
 *
 * The ``alwaysVisible`` flag locks this column at the front of the
 * left-pinned list and excludes it from the column-manager menu.
 */
const SELECT_DESCRIPTOR: DataTableColumnDef<unknown> = {
  id: 'select',
  meta: {
    alwaysVisible: true,
    enableResizing: false,
    enablePinning: false,
  },
} as DataTableColumnDef<unknown>

/**
 * Single source of truth for the column list every column composable
 * (visibility, order, pinning, sizing) consumes. When
 * ``enableRowSelection`` is true and the caller hasn't already supplied
 * a ``select`` column, we prepend the synthetic descriptor so its
 * ``id`` lands at the front of derived ``columnOrder`` and
 * ``columnPinning``.
 *
 * Defensive: if a caller hand-rolls a ``select`` column (with a custom
 * header / cell), we leave it alone — the caller's column wins.
 */
export function useAugmentedColumns<T>(
  columns: MaybeRefOrGetter<DataTableColumnDef<T>[]>,
  enableRowSelection: boolean,
): ComputedRef<DataTableColumnDef<unknown>[]> {
  const columnsGetter = () => toValue(columns)
  return computed(() => {
    const user = columnsGetter() as DataTableColumnDef<unknown>[]
    if (!enableRowSelection) return user
    const hasSelect = user.some(
      (c) =>
        (c.id ?? (c as { accessorKey?: string }).accessorKey) === 'select',
    )
    if (hasSelect) return user
    return [SELECT_DESCRIPTOR, ...user]
  })
}

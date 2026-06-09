import {
  computed,
  toValue,
  type ComputedRef,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue'
import { useStorage } from '@vueuse/core'
import type { ColumnPinningState } from '@tanstack/vue-table'
import type { DataTableColumnDef } from './types'

export type PinSide = 'left' | false

export interface ColumnPinning {
  userPinning: Ref<ColumnPinningState>
  columnPinning: ComputedRef<ColumnPinningState>
  hasOverrides: ComputedRef<boolean>
  togglePinColumn: (id: string, side: PinSide) => void
  reset: () => void
}

/**
 * Per-tenant per-browser column pinning, keyed by ``tableId``. Sliced
 * out of ``useColumnManager`` so each column concern lives in its own
 * single-responsibility composable behind a unified facade.
 *
 * Two invariants are pinned by the test suite (PR #90, incident
 * 2026-05-07):
 *   1. ``alwaysVisible`` columns lock at the FRONT of left-pinned
 *      regardless of user pinning — TanStack renders pinned-left
 *      BEFORE non-pinned columns, so without this the selection
 *      checkbox would drop behind any user-pinned column.
 *   2. ``identifier`` columns auto-pin to the left when no user
 *      pinning exists, so the row identity stays anchored while
 *      scrolling right. The first user pin yields, but ``alwaysVisible``
 *      stays.
 *
 * Right-side pinning was removed end-to-end in PR #88; legacy
 * ``right: [...]`` entries are filtered into ``[]`` on derivation and
 * overwritten on the next pin interaction. TanStack's
 * ``ColumnPinningState`` type still requires both fields, hence the
 * ``right: []`` carrier.
 */
export function useColumnPinning<T>(
  tableId: string,
  augmentedColumns: MaybeRefOrGetter<DataTableColumnDef<T>[]>,
): ColumnPinning {
  const userPinning = useStorage<ColumnPinningState>(
    `dt:${tableId}:pinning`,
    { left: [], right: [] },
    undefined,
    { mergeDefaults: true },
  )

  const columnPinning = computed<ColumnPinningState>(() => {
    const cols = toValue(augmentedColumns) as DataTableColumnDef<unknown>[]
    const declared = new Set(
      cols
        .map(
          (c) =>
            (c.id ?? (c as { accessorKey?: string }).accessorKey) as string,
        )
        .filter(Boolean),
    )

    const alwaysVisibleLeft = cols
      .filter((c) => c.meta?.alwaysVisible)
      .map(
        (c) =>
          (c.id ?? (c as { accessorKey?: string }).accessorKey) as string,
      )
      .filter(Boolean)
    const alwaysVisibleSet = new Set(alwaysVisibleLeft)

    const userLeft = (userPinning.value.left ?? []).filter(
      (id) => declared.has(id) && !alwaysVisibleSet.has(id),
    )

    if (userLeft.length === 0) {
      const identifierLeft = cols
        .filter((c) => c.meta?.identifier && !c.meta?.alwaysVisible)
        .map(
          (c) =>
            (c.id ?? (c as { accessorKey?: string }).accessorKey) as string,
        )
        .filter(Boolean)
      return { left: [...alwaysVisibleLeft, ...identifierLeft], right: [] }
    }
    return { left: [...alwaysVisibleLeft, ...userLeft], right: [] }
  })

  const hasOverrides = computed(
    () => (userPinning.value.left?.length ?? 0) > 0,
  )

  function togglePinColumn(id: string, side: PinSide) {
    const left = new Set(
      (userPinning.value.left ?? []).filter((x) => x !== id),
    )
    if (side === 'left') left.add(id)
    userPinning.value = { left: [...left], right: [] }
  }

  function reset() {
    userPinning.value = { left: [], right: [] }
  }

  return {
    userPinning,
    columnPinning,
    hasOverrides,
    togglePinColumn,
    reset,
  }
}

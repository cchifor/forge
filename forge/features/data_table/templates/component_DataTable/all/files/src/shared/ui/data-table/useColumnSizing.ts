import { computed, type ComputedRef, type Ref } from 'vue'
import { useStorage } from '@vueuse/core'

/**
 * Per-tenant per-browser column widths, keyed by ``tableId``. Sliced
 * out of ``useColumnManager`` so the four column concerns (visibility,
 * order, pinning, sizing) live in single-responsibility composables
 * behind a unified facade.
 *
 * Sizing is a passthrough: there's no derivation logic — the user's
 * persisted widths are exactly what TanStack consumes. Reset clears the
 * map; rehydration on construction picks up any prior widths.
 */
export interface ColumnSizing {
  userSizing: Ref<Record<string, number>>
  columnSizing: ComputedRef<Record<string, number>>
  hasOverrides: ComputedRef<boolean>
  setColumnSizing: (next: Record<string, number>) => void
  reset: () => void
}

export function useColumnSizing(tableId: string): ColumnSizing {
  const userSizing = useStorage<Record<string, number>>(
    `dt:${tableId}:sizing`,
    {},
    undefined,
    { mergeDefaults: true },
  )

  const columnSizing = computed(() => ({ ...userSizing.value }))
  const hasOverrides = computed(
    () => Object.keys(userSizing.value).length > 0,
  )

  function setColumnSizing(next: Record<string, number>) {
    userSizing.value = { ...next }
  }

  function reset() {
    userSizing.value = {}
  }

  return {
    userSizing,
    columnSizing,
    hasOverrides,
    setColumnSizing,
    reset,
  }
}

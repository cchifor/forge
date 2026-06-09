import {
  computed,
  ref,
  toValue,
  type ComputedRef,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue'
import { useStorage } from '@vueuse/core'
import type { VisibilityState } from '@tanstack/vue-table'
import type { DataTableColumnDef } from './types'
import {
  BP_WIDTH,
  twBelow,
  useTwBreakpoint,
  type TailwindBreakpoint,
} from './breakpoints'

export interface ColumnVisibility {
  /** Persisted intent map. ``true`` = explicitly shown, ``false`` = explicitly hidden, absent = default. */
  userVisibility: Ref<Record<string, boolean>>
  /**
   * Form-binding state. For every togglable column, ``true`` unless
   * ``userVisibility[id] === false``. Defaults to all-checked
   * regardless of layout — the popover always reflects user intent.
   */
  userVisibilityIntent: ComputedRef<Record<string, boolean>>
  /** Effective state TanStack consumes. User override > responsive hint > shown. */
  columnVisibility: ComputedRef<VisibilityState>
  /** ``true`` iff any user-hidden column exists. Drives the trigger-button indicator. */
  hasUserHiddenColumns: ComputedRef<boolean>
  /** ``true`` iff any user value (true or false) exists. Drives the menu's "Reset" button. */
  hasOverrides: ComputedRef<boolean>
  toggleColumn: (id: string, visible: boolean) => void
  reset: () => void
}

/**
 * Per-tenant per-browser column visibility, keyed by ``tableId``.
 *
 * Three-state semantics:
 *   - **Form intent** (``userVisibilityIntent``) — what the popover
 *     binds to. Defaults to ``true`` for every togglable column. Only
 *     reflects user toggles; the runtime layout adjustment from
 *     ``responsiveHidden`` is invisible to it.
 *   - **Effective** (``columnVisibility``) — what the table renders.
 *     User override beats the responsive hint, which beats default-shown.
 *   - **Indicator** (``hasUserHiddenColumns``) — true iff any column
 *     was explicitly hidden by the user. Drives the trigger-button dot
 *     so users know they've filtered the table down.
 *
 * The form and effective state can disagree when ``responsiveHidden``
 * is active at narrow container widths — by design. Mental model: "I
 * haven't filtered anything; the table just adjusted to fit."
 *
 * ``toggleColumn`` always writes explicit ``true`` or ``false`` (never
 * deletes). Re-checking a responsively-hidden column needs the
 * explicit ``true`` to override the layout hint; without it,
 * "uncheck → recheck" would leave the column hidden by the hint and
 * confuse users.
 */
export function useColumnVisibility<T>(
  tableId: string,
  augmentedColumns: MaybeRefOrGetter<DataTableColumnDef<T>[]>,
  options?: { containerWidth?: Ref<number> },
): ColumnVisibility {
  const { tw } = useTwBreakpoint()
  const containerWidth = options?.containerWidth ?? ref(0)

  const userVisibility = useStorage<Record<string, boolean>>(
    `dt:${tableId}:cols`,
    {},
    undefined,
    { mergeDefaults: true },
  )

  function isResponsivelyHidden(threshold: TailwindBreakpoint): boolean {
    if (containerWidth.value > 0) {
      return containerWidth.value < BP_WIDTH[threshold]
    }
    return twBelow(tw.value, threshold)
  }

  function isListTier(): boolean {
    if (containerWidth.value > 0) return containerWidth.value < BP_WIDTH.sm
    return twBelow(tw.value, 'sm')
  }

  const userVisibilityIntent = computed<Record<string, boolean>>(() => {
    const out: Record<string, boolean> = {}
    const cols = toValue(augmentedColumns) as DataTableColumnDef<unknown>[]
    for (const col of cols) {
      if (col.meta?.alwaysVisible) continue
      const id = (col.id ??
        (col as { accessorKey?: string }).accessorKey) as string
      if (!id) continue
      out[id] = userVisibility.value[id] !== false
    }
    return out
  })

  const columnVisibility = computed<VisibilityState>(() => {
    const state: VisibilityState = {}
    const cols = toValue(augmentedColumns) as DataTableColumnDef<unknown>[]
    for (const col of cols) {
      const id = (col.id ??
        (col as { accessorKey?: string }).accessorKey) as string
      if (!id) continue
      // ``cardSubtitle`` columns are list-tier-only — they contribute
      // the subtitle line in the card layout and would be a meaningless
      // empty column on the wide / compact tiers. Auto-hide whenever
      // we're NOT in the list tier; user toggles can't override (the
      // column has no header so there's nothing sensible to choose).
      if (col.meta?.cardSubtitle && !isListTier()) {
        state[id] = false
        continue
      }
      const userSet = userVisibility.value[id]
      if (userSet !== undefined) {
        state[id] = userSet
        continue
      }
      const below = col.meta?.responsiveHidden?.below
      state[id] = !(below && isResponsivelyHidden(below))
    }
    return state
  })

  const hasUserHiddenColumns = computed(() =>
    Object.values(userVisibility.value).some((v) => v === false),
  )

  const hasOverrides = computed(
    () => Object.keys(userVisibility.value).length > 0,
  )

  function toggleColumn(id: string, visible: boolean) {
    userVisibility.value = { ...userVisibility.value, [id]: visible }
  }

  function reset() {
    userVisibility.value = {}
  }

  return {
    userVisibility,
    userVisibilityIntent,
    columnVisibility,
    hasUserHiddenColumns,
    hasOverrides,
    toggleColumn,
    reset,
  }
}

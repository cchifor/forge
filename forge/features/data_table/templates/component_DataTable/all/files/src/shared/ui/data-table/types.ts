import type { ColumnDef } from '@tanstack/vue-table'
import type { InjectionKey } from 'vue'
import type { TailwindBreakpoint } from '@/shared/composables/useBreakpoint'

/** Three rendering tiers DataTable picks based on its container width. */
export type DataTableLayout = 'list' | 'compact' | 'wide'

/**
 * Inject token for DataTable's current layout tier. Cells use this to
 * adapt rendering without knowing about TanStack's CellContext —
 * primarily so the hero ``DataSourceNameCell`` can collapse its
 * subtitle on the list (mobile) tier where the secondary metadata
 * line covers the same ground.
 */
export const DATA_TABLE_LAYOUT: InjectionKey<{ value: DataTableLayout }> =
  Symbol('DataTableLayout')

/**
 * Extra column metadata understood by `<DataTable>`:
 *
 * - `responsiveHidden.below` — auto-hide the column below the given Tailwind
 *   breakpoint. The threshold is resolved against the **table's container
 *   width** (via ResizeObserver), not the viewport — so a chat panel sliding
 *   in narrows the table's available space and hides low-priority columns
 *   without the window resizing. User toggles from the column-visibility
 *   menu always win over this hint.
 * - `alwaysVisible` — the column cannot be hidden by the user and is not
 *   listed in the column-visibility menu (use for selection checkboxes or
 *   per-row action columns).
 * - `cardLabel` — label to render in mobile card mode. Defaults to the
 *   column's `header` when it's a string.
 * - `sortable` — short for `enableSorting` (preserved for ergonomic column
 *   defs; TanStack's `enableSorting` still works).
 */
export interface DataTableColumnMeta {
  responsiveHidden?: { below: TailwindBreakpoint }
  alwaysVisible?: boolean
  cardLabel?: string
  /** When true, the cell content spans the full card width (no label column). */
  cardHero?: boolean
  /**
   * When true, the column's rendered cell becomes the **list-tier
   * subtitle** — the fixed-text second-row label that prefixes the
   * secondary metadata (e.g. "Sample" / "Manual" / "Custom (advanced)"
   * for data sources, the trigger type for workflows, the provider
   * class for integrations). The column is then excluded from the
   * card's secondary-cell list so its content doesn't appear twice.
   *
   * Combined with ``responsiveHidden: { below: 'sm' }`` (or similar)
   * a column can serve as the mobile subtitle without polluting the
   * compact / wide tiers.
   *
   * Why a column-meta flag (not a DataTable prop): keeps the table
   * generic. Every consumer wires its own subtitle source via the
   * column-definition surface they already own; ``<DataTable>``
   * stays free of feature-specific props.
   */
  cardSubtitle?: boolean
  /** Opt the column out of resizing (default: true). Set `false` on fixed-width columns like selection checkboxes. */
  enableResizing?: boolean
  /** Opt the column out of pinning (default: true). Set `false` on the selection column. */
  enablePinning?: boolean
  /**
   * "Primary identifier" for the row — Name, Title, Display name, etc.
   * Auto-pinned to the left so users always see what each row IS while
   * scrolling right. User pins from the column-manager menu override
   * this default (any non-empty `userPinning.left` or `userPinning.right`
   * disables the auto-derivation entirely; "Reset" restores it).
   *
   * Distinct from `cardHero` (mobile-card layout): a column can be one,
   * the other, or both. Hero is "biggest cell on a card", identifier is
   * "the column you must always see in a wide table".
   */
  identifier?: boolean
}

export type DataTableColumnDef<T> = ColumnDef<T, unknown> & {
  meta?: DataTableColumnMeta
}

export type DataTableMode = 'pagination' | 'infinite'

<script setup lang="ts" generic="T extends { id: string }">
/**
 * Container-aware data table.
 *
 * The component picks one of three layouts based on its **own container
 * width** (measured via ResizeObserver, not the viewport):
 *
 *   <  640 px → 'list'    — vertical card list with a sort-chip above
 *   < 1024 px → 'compact' — table with low-priority columns auto-hidden
 *   ≥ 1024 px → 'wide'    — full table with resize/pin grips
 *
 * No horizontal scroll — the wrapper is `overflow-x-clip`. If a user resizes
 * a column past the container the right edge clips and the column-manager
 * menu is the escape hatch (visible at every tier).
 */
import { computed, onBeforeUnmount, provide, reactive, ref, toRef, useSlots, watch } from 'vue'
import {
  FlexRender,
  type Column,
  type Row,
  type RowSelectionState,
} from '@tanstack/vue-table'
import { useIntersectionObserver } from '@vueuse/core'
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import { useContainerSize } from '@/shared/composables/useContainerSize'
import { useDataTable } from './useDataTable'
import type { ColumnManager } from './useColumnManager'
import SortChip from './SortChip.vue'
import {
  DATA_TABLE_LAYOUT,
  type DataTableColumnDef,
  type DataTableLayout,
  type DataTableMode,
} from './types'

interface Props {
  columns: DataTableColumnDef<T>[]
  rows: T[]
  tableId: string
  /**
   * Hoisted column manager. The page typically calls
   * `useColumnManager(tableId, columns, { enableRowSelection: ... })` once
   * and passes the handle into both `<ColumnManagerMenu>` (in its
   * FilterBar) and `<DataTable>` here, so the menu and the table never
   * disagree about visibility / order / pinning. Optional — when omitted,
   * `useDataTable` instantiates one internally (back-compat path).
   */
  manager?: ColumnManager
  rowSelection?: RowSelectionState
  /**
   * Used only when `manager` is not supplied — the manager is the single
   * source of truth for whether the select column appears.
   */
  enableRowSelection?: boolean
  /** Controlled global filter text. */
  globalFilter?: string
  globalFilterFn?: Parameters<typeof useDataTable<T>>[0]['globalFilterFn']
  loading?: boolean
  error?: string | null
  /** `infinite` scrolls a sentinel that emits `load-more`; `pagination` renders a pager. */
  mode?: DataTableMode
  hasNextPage?: boolean
  isFetchingNextPage?: boolean
  pageSize?: number
  initialSorting?: Parameters<typeof useDataTable<T>>[0]['initialSorting']
  /** aria-label for the table element; also used for the empty state. */
  ariaLabel?: string
  /** Classes applied to each row / card — useful for status tinting. */
  rowClass?: (row: T) => string | string[] | Record<string, boolean>
  /** Highlight a focused row id (keyboard nav). */
  focusedId?: string | null
  /**
   * Taxonomy prefix for per-row `data-test` attributes. When set, every
   * row (list-tier `<li>` and table-tier `<tr>`) gets
   * `data-test="${rowTestIdPrefix}-${row.original.id}"`. The pre-existing
   * `data-row-id` attribute stays untouched so internal callsites that
   * rely on it (e.g. column-manager keyboard nav) keep working — this
   * is purely additive for e2e selectors.
   */
  rowTestIdPrefix?: string
}

const props = withDefaults(defineProps<Props>(), {
  mode: 'infinite',
  // Vue's runtime defaults Boolean props to `false` when absent — explicit
  // `true` here so callers that don't pass the prop still get the historical
  // selection-enabled default. Ignored anyway when a `manager` prop is
  // supplied (the manager's `enableRowSelection` wins; see useDataTable).
  enableRowSelection: true,
})

const emit = defineEmits<{
  'row-click': [row: T]
  'update:row-selection': [state: RowSelectionState]
  'update:global-filter': [value: string]
  'load-more': []
}>()

// ---------------------------------------------------------------------------
// Container-driven layout
// ---------------------------------------------------------------------------

const wrapperEl = ref<HTMLElement | null>(null)
const { width: containerWidth } = useContainerSize(wrapperEl)

/**
 * Default to 'wide' before the first ResizeObserver measurement so the
 * initial paint on a desktop browser doesn't briefly flash card mode.
 */
const layout = computed<DataTableLayout>(() => {
  const w = containerWidth.value
  if (w === 0) return 'wide'
  if (w < 640) return 'list'
  if (w < 1024) return 'compact'
  return 'wide'
})

const isList = computed(() => layout.value === 'list')

// Cells reach for the layout via inject — provides a clean way for
// e.g. ``DataSourceNameCell`` to collapse its subtitle on the list
// tier without having to know about TanStack's CellContext shape.
// ``reactive`` keeps the object identity stable so consumers' inject
// keeps tracking, while ``layout`` updates flow through the watcher.
const layoutHolder = reactive<{ value: DataTableLayout }>({ value: layout.value })
provide(DATA_TABLE_LAYOUT, layoutHolder)
watch(layout, (next) => {
  layoutHolder.value = next
})

// ---------------------------------------------------------------------------
// Table state
// ---------------------------------------------------------------------------

const selectionRef = ref<RowSelectionState>(props.rowSelection ?? {})
const globalFilterRef = ref<string | undefined>(props.globalFilter)

const {
  table,
  manager,
  userSizing,
  hasNoMatches,
} = useDataTable<T>({
  columns: toRef(props, 'columns'),
  rows: toRef(props, 'rows'),
  tableId: props.tableId,
  manager: props.manager,
  selection: selectionRef,
  onSelectionChange: (next) => emit('update:row-selection', next),
  globalFilter: globalFilterRef,
  initialSorting: props.initialSorting,
  enableRowSelection: props.enableRowSelection ?? true,
  globalFilterFn: props.globalFilterFn,
  pageSize: props.mode === 'pagination' ? (props.pageSize ?? 25) : undefined,
})

// Forward the table's container width into the manager so its
// `responsiveHidden` derivation reacts to layout changes (e.g. the AI
// chat panel sliding in narrows the table without resizing the window).
// `immediate: true` because the manager defaults to width 0 (which falls
// back to viewport breakpoints) — the first measurement should land
// before the table renders its first row.
watch(
  containerWidth,
  (w) => manager.setContainerWidth(w),
  { immediate: true },
)

watch(
  () => props.rowSelection,
  (next) => {
    if (next && next !== selectionRef.value) selectionRef.value = next
  },
)
watch(
  () => props.globalFilter,
  (next) => {
    globalFilterRef.value = next
  },
)

const slots = useSlots()
const hasRowActionsSlot = computed(() => !!slots['row-actions'])
const hasExpandedRowSlot = computed(() => !!slots['expanded-row'])

// ---------------------------------------------------------------------------
// Pinned-cell sticky helpers (table tier)
// ---------------------------------------------------------------------------

function pinBinding(column: Column<T, unknown>, isHeader = false) {
  // Internal z-stack (scoped to the wrapper's `isolation: isolate`):
  //   pinned thead intersection   z-[25]   (sticky top + sticky left)
  //   thead                       z-20
  //   pinned body cells           z-10
  //   regular body cells          0
  // The wrapper's `isolate` class confines this stack so it can't leak
  // past the table — sibling page chrome (sticky FilterBar, AppHeader,
  // modals) coordinates only on the wrapper's outer z-auto, never on
  // these internal values. Header cells paint in `bg-muted` so the
  // thead's glass treatment is continuous across pinned columns; body
  // pinned cells paint in `bg-card`.
  const bgClass = isHeader ? 'bg-muted' : 'bg-card'
  const zClass = isHeader ? 'z-[25]' : 'z-10'
  if (column.getIsPinned() === 'left') {
    return {
      class: `sticky ${zClass} ${bgClass} data-[pinned-last=true]:shadow-[inset_-1px_0_0_theme(colors.border)]`,
      style: { left: `${column.getStart('left')}px` },
      dataPinned: 'left',
      dataPinnedLast: column.getIsLastColumn('left'),
    }
  }
  return {
    class: '',
    style: {},
    dataPinned: undefined,
    dataPinnedLast: undefined,
  }
}

function sizeBinding(id: string) {
  const width = userSizing.value[id]
  return width ? { width: `${width}px` } : {}
}

// ---------------------------------------------------------------------------
// Card-tier helpers
// ---------------------------------------------------------------------------

const heroColumnId = computed(() => {
  const hero = props.columns.find((c) => c.meta?.cardHero)
  if (hero) return hero.id ?? (hero as { accessorKey?: string }).accessorKey
  return props.columns.find(
    (c) => !c.meta?.alwaysVisible && 'accessorKey' in (c as object),
  )?.id
})

function heroCell(row: Row<T>) {
  return row
    .getVisibleCells()
    .find((cell) => cell.column.id === heroColumnId.value)
}

function selectionCell(row: Row<T>) {
  return row.getVisibleCells().find((cell) => cell.column.id === 'select')
}

/**
 * Cell flagged via ``meta.cardSubtitle`` for the list-tier subtitle
 * line (e.g. "Sample" / "Manual" / "Custom (advanced)" for data
 * sources). At most one column carries this flag; the first match
 * wins. Returns ``null`` when no column opts in — list tier then
 * falls back to the joined-secondary-cells layout.
 */
function subtitleCell(row: Row<T>) {
  return (
    row.getVisibleCells().find((cell) => {
      const col = cell.column.columnDef as DataTableColumnDef<T>
      return col.meta?.cardSubtitle === true
    }) ?? null
  )
}

/** Non-hero, non-select, non-subtitle visible cells — the "secondary metadata" line. */
function secondaryCellsForCard(row: Row<T>) {
  return row.getVisibleCells().filter((cell) => {
    const col = cell.column.columnDef as DataTableColumnDef<T>
    if (col.meta?.alwaysVisible) return false // skip select
    if (col.meta?.cardSubtitle) return false // rendered separately as subtitle
    if (cell.column.id === heroColumnId.value) return false
    return true
  })
}

// ---------------------------------------------------------------------------
// Row click / keyboard handling
// ---------------------------------------------------------------------------

function isNonInteractiveTarget(e: MouseEvent): boolean {
  const el = e.target as HTMLElement | null
  if (!el) return true
  return !el.closest('[data-row-ignore-click]')
}

function onRowClick(row: Row<T>, e: MouseEvent) {
  if (!isNonInteractiveTarget(e)) return
  emit('row-click', row.original)
}

function onRowKeydown(row: Row<T>, e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    emit('row-click', row.original)
  }
}

// ---------------------------------------------------------------------------
// List-tier overflow detection (single shared ResizeObserver)
// ---------------------------------------------------------------------------

/**
 * The list tier renders 2 visual rows by default — title, then a
 * single line containing subtitle + secondary cells. When that
 * second line doesn't fit on a single line we fall back to 3 rows
 * (subtitle on its own line, secondary cells below).
 *
 * One ResizeObserver covers every row 2 element through the same
 * instance — observing 200+ row divs through individual
 * ``useResizeObserver`` hooks would create 200+ observers, which
 * the browser dislikes. The collected DOM-based ``data-overflow``
 * attribute drives the CSS branch so we don't pay re-render cost
 * on every resize either.
 */
const overflowObserver = ref<ResizeObserver | null>(null)
const observedSecondaryEls = new Set<HTMLElement>()

function ensureOverflowObserver(): ResizeObserver | null {
  if (overflowObserver.value) return overflowObserver.value
  // SSR + jsdom-based unit tests don't ship ResizeObserver. Without
  // overflow tracking the row stays in the (correct) 2-row default
  // — degrading exactly the way ``useContainerSize`` already does.
  if (typeof ResizeObserver === 'undefined') return null
  const obs = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const el = entry.target as HTMLElement
      // ``+ 1`` slack absorbs sub-pixel rounding so a row that
      // exactly fills its container doesn't oscillate between 2
      // and 3 rows on every resize tick.
      const overflows = el.scrollWidth > el.clientWidth + 1
      if (overflows) {
        el.dataset.overflow = 'true'
      } else {
        delete el.dataset.overflow
      }
    }
  })
  overflowObserver.value = obs
  return obs
}

function registerSecondary(el: Element | null | undefined): void {
  if (!(el instanceof HTMLElement)) return
  if (observedSecondaryEls.has(el)) return
  const obs = ensureOverflowObserver()
  if (!obs) return
  obs.observe(el)
  observedSecondaryEls.add(el)
}

onBeforeUnmount(() => {
  overflowObserver.value?.disconnect()
  overflowObserver.value = null
  observedSecondaryEls.clear()
})

// ---------------------------------------------------------------------------
// Infinite-scroll sentinel
// ---------------------------------------------------------------------------

const sentinel = ref<HTMLElement | null>(null)
useIntersectionObserver(
  sentinel,
  ([entry]) => {
    if (
      entry?.isIntersecting &&
      props.hasNextPage &&
      !props.isFetchingNextPage
    ) {
      emit('load-more')
    }
  },
  { threshold: 0 },
)
</script>

<template>
  <div ref="wrapperEl" class="dt-root flex flex-col gap-2">
    <!--
      The DataTable owns no toolbar of its own — the column manager menu
      and any bulk-action chrome live in the page's `FilterBarShell` (the
      page is the canonical "table toolbar"). The page hoists a single
      `useColumnManager` instance and passes it via the `manager` prop, so
      the FilterBar's `<ColumnManagerMenu>` and this table share state.
    -->

    <!-- Loading -->
    <div v-if="loading" class="overflow-hidden rounded-xl border bg-card">
      <slot name="loading">
        <div class="divide-y">
          <div
            v-for="i in 6"
            :key="i"
            class="h-14 animate-pulse bg-muted/30"
          />
        </div>
      </slot>
    </div>

    <!-- Error -->
    <div
      v-else-if="error"
      class="rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive"
    >
      <slot name="error" :message="error">
        <div class="font-medium">Couldn't load data</div>
        <div class="mt-0.5 text-xs">{{ error }}</div>
      </slot>
    </div>

    <!-- Empty -->
    <div
      v-else-if="rows.length === 0"
      class="rounded-xl border bg-card p-8 text-center text-sm text-muted-foreground"
    >
      <slot name="empty">No results</slot>
    </div>

    <!-- LIST TIER (< 640 px container) -->
    <template v-else-if="isList">
      <div class="flex flex-wrap items-center gap-2">
        <SortChip :table="table" />
        <div class="ml-auto text-xs text-muted-foreground">
          {{ rows.length.toLocaleString() }}
          row{{ rows.length === 1 ? '' : 's' }}
        </div>
      </div>

      <ul
        class="dt-list flex flex-col gap-2"
        :aria-label="ariaLabel"
      >
        <template
          v-for="row in table.getRowModel().rows"
          :key="row.id"
        >
        <li
          :class="[
            'group flex min-h-[64px] items-center gap-3 rounded-xl border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
            focusedId === row.original.id &&
              'ring-1 ring-inset ring-primary/40',
            row.getIsSelected() && 'bg-primary/[0.04]',
            typeof rowClass === 'function' ? rowClass(row.original) : '',
          ]"
          tabindex="0"
          role="button"
          :data-row-id="row.original.id"
          :data-test="rowTestIdPrefix ? `${rowTestIdPrefix}-${row.original.id}` : undefined"
          @click="(e) => onRowClick(row, e)"
          @keydown="(e) => onRowKeydown(row, e)"
        >
          <div
            v-if="selectionCell(row)"
            data-row-ignore-click
            class="-ml-1 flex h-11 w-11 shrink-0 items-center justify-center"
            @click.stop
          >
            <FlexRender
              :render="selectionCell(row)!.column.columnDef.cell"
              :props="selectionCell(row)!.getContext()"
            />
          </div>

          <div class="min-w-0 flex-1">
            <div class="truncate font-medium">
              <FlexRender
                v-if="heroCell(row)"
                :render="heroCell(row)!.column.columnDef.cell"
                :props="heroCell(row)!.getContext()"
              />
            </div>
            <!--
              Row 2 carries the column-declared subtitle (any column
              with ``meta.cardSubtitle: true``, e.g. Sample / Manual /
              Custom (advanced) for data sources, the trigger type for
              workflows, the provider class for integrations) plus the
              secondary-cell summary. The shared ResizeObserver flips
              ``data-overflow="true"`` on this div when its scroll
              width exceeds its client width; the CSS rule below splits
              subtitle off into its own line for that row only, giving
              the user a 3-row card without forcing every other row to
              grow. The subtitle cell is excluded from the secondary
              loop (see ``secondaryCellsForCard``) so it isn't
              rendered twice.
            -->
            <div
              v-if="subtitleCell(row) || secondaryCellsForCard(row).length > 0"
              :ref="(el) => registerSecondary(el as Element | null | undefined)"
              :data-row-secondary="row.original.id"
              class="dt-list-secondary mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <span
                v-if="subtitleCell(row)"
                class="dt-list-subtitle shrink-0 truncate"
              >
                <FlexRender
                  :render="subtitleCell(row)!.column.columnDef.cell"
                  :props="subtitleCell(row)!.getContext()"
                />
              </span>
              <template
                v-for="(cell, idx) in secondaryCellsForCard(row)"
                :key="cell.id"
              >
                <span
                  v-if="subtitleCell(row) || idx > 0"
                  aria-hidden="true"
                  class="opacity-50"
                >·</span>
                <span class="inline-flex min-w-0 items-center">
                  <FlexRender
                    :render="cell.column.columnDef.cell"
                    :props="cell.getContext()"
                  />
                </span>
              </template>
            </div>
          </div>

          <div
            v-if="hasRowActionsSlot"
            data-row-ignore-click
            class="shrink-0"
            @click.stop
          >
            <slot name="row-actions" :row="row.original" :layout="layout" />
          </div>

          <ChevronRight
            class="shrink-0 h-4 w-4 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5"
          />
        </li>
        <li v-if="hasExpandedRowSlot" class="list-none">
          <slot name="expanded-row" :row="row.original" />
        </li>
        </template>
        <li
          v-if="hasNoMatches"
          class="rounded-xl border bg-card px-3 py-10 text-center text-sm text-muted-foreground"
        >
          <slot name="no-matches">No matches</slot>
        </li>
      </ul>
    </template>

    <!-- TABLE TIER (compact / wide) — embedded in the page; the page-scroll
         container in MainLayout (`<main> > div.overflow-auto`) is the single
         scrollport. The wrapper has NO overflow utilities, so `position:
         sticky` on <thead> resolves against the page scroll container.
         The thead's `top` reads from `--dt-thead-top`, a CSS var the page
         sets to the height of any sticky chrome that sits above the table
         (e.g. a sticky FilterBar). Default 0px puts the thead flush at
         the top of the page-scroll container (which is right below the
         AppHeader). Wide tables rely on `meta.responsiveHidden` to hide
         low-priority columns at narrow widths. -->
    <div
      v-else
      class="isolate rounded-xl border border-border/60 bg-card"
    >
      <table class="w-full text-sm" :aria-label="ariaLabel">
        <thead
          class="sticky top-[var(--dt-thead-top,0px)] z-20 bg-muted/95 backdrop-blur shadow-[0_1px_0_0_theme(colors.border)] supports-[backdrop-filter]:bg-muted/70"
        >
          <tr>
            <th
              v-for="header in table.getHeaderGroups()[0].headers"
              :key="header.id"
              :class="[
                'relative px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground',
                header.column.id === 'select' ? 'w-10 pl-4 pr-0' : '',
                header.column.getCanSort()
                  ? 'cursor-pointer select-none hover:text-foreground'
                  : '',
                pinBinding(header.column, true).class,
              ]"
              :style="{
                ...pinBinding(header.column, true).style,
                ...sizeBinding(header.column.id),
              }"
              :data-pinned="pinBinding(header.column, true).dataPinned"
              :data-pinned-last="pinBinding(header.column, true).dataPinnedLast"
              @click="header.column.getToggleSortingHandler()?.($event)"
            >
              <div class="flex items-center gap-1">
                <FlexRender
                  :render="header.column.columnDef.header"
                  :props="header.getContext()"
                />
                <template v-if="header.column.getCanSort()">
                  <ArrowUp
                    v-if="header.column.getIsSorted() === 'asc'"
                    class="h-3 w-3"
                  />
                  <ArrowDown
                    v-else-if="header.column.getIsSorted() === 'desc'"
                    class="h-3 w-3"
                  />
                  <ArrowUpDown v-else class="h-3 w-3 opacity-30" />
                </template>
              </div>
              <div
                v-if="header.column.getCanResize()"
                :class="[
                  'dt-resize-grip absolute right-0 top-0 h-full w-1.5 cursor-col-resize select-none touch-none',
                  header.column.getIsResizing()
                    ? 'bg-primary/70'
                    : 'hover:bg-primary/40',
                ]"
                role="separator"
                :aria-label="`Resize ${header.column.id}`"
                @click.stop
                @mousedown="header.getResizeHandler()($event)"
                @touchstart="header.getResizeHandler()($event)"
              />
            </th>
            <th
              v-if="hasRowActionsSlot"
              class="w-10 px-2 py-2"
              aria-label="Row actions"
            />
          </tr>
        </thead>
        <tbody>
          <template
            v-for="row in table.getRowModel().rows"
            :key="row.id"
          >
          <tr
            :data-row-id="row.original.id"
            :data-test="rowTestIdPrefix ? `${rowTestIdPrefix}-${row.original.id}` : undefined"
            :class="[
              'group border-t transition-[background-color] duration-150 hover:bg-muted/30',
              focusedId === row.original.id &&
                'ring-1 ring-inset ring-primary/40',
              row.getIsSelected() && 'bg-primary/[0.04]',
              typeof rowClass === 'function' ? rowClass(row.original) : '',
            ]"
            tabindex="0"
            role="button"
            @click="(e) => onRowClick(row, e)"
            @keydown="(e) => onRowKeydown(row, e)"
          >
            <td
              v-for="cell in row.getVisibleCells()"
              :key="cell.id"
              :class="[
                'align-middle',
                cell.column.id === 'select'
                  ? 'w-10 pl-4 pr-0'
                  : 'px-4 py-3',
                pinBinding(cell.column).class,
              ]"
              :style="{
                ...pinBinding(cell.column).style,
                ...sizeBinding(cell.column.id),
              }"
              :data-pinned="pinBinding(cell.column).dataPinned"
              :data-pinned-last="pinBinding(cell.column).dataPinnedLast"
              :data-row-ignore-click="
                cell.column.id === 'select' ? '' : undefined
              "
              @click="
                cell.column.id === 'select'
                  ? $event.stopPropagation()
                  : undefined
              "
            >
              <div class="truncate">
                <FlexRender
                  :render="cell.column.columnDef.cell"
                  :props="cell.getContext()"
                />
              </div>
            </td>
            <td
              v-if="hasRowActionsSlot"
              class="px-2 py-3 text-right align-middle"
              data-row-ignore-click
              @click.stop
            >
              <slot name="row-actions" :row="row.original" :layout="layout" />
            </td>
          </tr>
          <tr v-if="hasExpandedRowSlot">
            <td
              :colspan="
                table.getHeaderGroups()[0].headers.length +
                (hasRowActionsSlot ? 1 : 0)
              "
              class="p-0"
            >
              <slot name="expanded-row" :row="row.original" />
            </td>
          </tr>
          </template>
          <tr v-if="hasNoMatches">
            <td
              :colspan="
                table.getHeaderGroups()[0].headers.length +
                (hasRowActionsSlot ? 1 : 0)
              "
              class="px-4 py-10 text-center text-sm text-muted-foreground"
            >
              <slot name="no-matches">No matches</slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Footer: pagination or infinite-scroll sentinel -->
    <template v-if="rows.length > 0 && !loading && !error">
      <div
        v-if="mode === 'pagination'"
        class="flex items-center justify-between gap-2 text-xs text-muted-foreground"
      >
        <div>
          Page {{ table.getState().pagination.pageIndex + 1 }} of
          {{ Math.max(1, table.getPageCount()) }}
        </div>
        <div class="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            class="h-8 px-2"
            :disabled="!table.getCanPreviousPage()"
            @click="table.previousPage()"
          >
            <ChevronLeft class="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="h-8 px-2"
            :disabled="!table.getCanNextPage()"
            @click="table.nextPage()"
          >
            <ChevronRight class="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div
        v-else-if="hasNextPage"
        ref="sentinel"
        class="flex items-center justify-center py-3 text-xs text-muted-foreground"
      >
        <Loader2
          v-if="isFetchingNextPage"
          class="mr-2 h-3.5 w-3.5 motion-safe:animate-spin"
        />
        <span v-if="isFetchingNextPage">Loading more…</span>
        <span v-else>Scroll for more</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* The resize grip is a pointer-device affordance. On coarse pointers
   (touch), column widths are driven by auto-layout and the column
   visibility menu — a 6-pixel drag target is useless there and easy
   to trigger by accident. */
@media (hover: none) and (pointer: coarse) {
  .dt-resize-grip {
    display: none;
  }
}

/* Cell content is always truncated, never wrapped, so a long value can't
   blow the column out beyond what the user (or auto-hide) configured. */
.dt-root td > div.truncate {
  max-width: 100%;
}

/* List-tier row 2: default is a single line that truncates. The
   shared ResizeObserver flips ``data-overflow="true"`` on this
   element when its scroll width exceeds its client width — at which
   point we wrap the content to a second visual line, growing the
   card to 3 rows for that single row only. Other rows whose row 2
   still fits stay at 2. */
.dt-list-secondary {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}

.dt-list-secondary[data-overflow='true'] {
  flex-wrap: wrap;
  white-space: normal;
}

/* The subtitle never gets squeezed to "…" — secondary cells
   truncate first; only when even the subtitle can't fit do we
   wrap. The shrink-0 on the subtitle handles the first half;
   ``min-w-0`` on the secondary cells lets them shrink under it. */
.dt-list-subtitle {
  font-weight: 500;
}
</style>

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, ref } from 'vue'

// `useContainerSize` is ResizeObserver-driven and jsdom doesn't lay out, so
// the real composable would always read 0. Stub it with a shared Vue ref the
// tests can mutate via `setContainerWidth(...)`. The mock factory runs lazily
// on first import — by then `vue` is loadable — and the returned `width` ref
// is captured in closure so every component instance sees the same value.
vi.mock('@/shared/composables/useContainerSize', async () => {
  const { ref } = await import('vue')
  const width = ref(1440)
  const height = ref(600)
  return {
    useContainerSize: () => ({ width, height }),
    __mockWidth: width,
  }
})

import * as ContainerSizeMock from '@/shared/composables/useContainerSize'
import DataTable from './DataTable.vue'
import { useColumnManager, type ColumnManager } from './useColumnManager'
import type { DataTableColumnDef } from './types'

const mockWidth = (
  ContainerSizeMock as unknown as { __mockWidth: { value: number } }
).__mockWidth

function setContainerWidth(width: number) {
  mockWidth.value = width
}

interface Row {
  id: string
  name: string
  age: number
  city: string
}

const rows: Row[] = [
  { id: '1', name: 'Ada', age: 30, city: 'London' },
  { id: '2', name: 'Grace', age: 40, city: 'New York' },
  { id: '3', name: 'Alan', age: 25, city: 'Manchester' },
]

function buildColumns(): DataTableColumnDef<Row>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: 'Name',
      enableSorting: true,
      cell: ({ row }) => h('span', row.original.name),
    },
    {
      id: 'age',
      accessorKey: 'age',
      header: 'Age',
      enableSorting: true,
      cell: ({ row }) => h('span', String(row.original.age)),
    },
    {
      id: 'city',
      accessorKey: 'city',
      header: 'City',
      meta: { responsiveHidden: { below: 'lg' } },
      cell: ({ row }) => h('span', row.original.city),
    },
  ]
}

/**
 * Page-style hoisted manager. Tests that exercise visibility / order /
 * pinning state mount `<DataTable>` with this handle so they can drive
 * the manager directly (mirroring how the real list pages work — see
 * `DataSourcesPage.vue`'s `columnManager`). Tests that only check
 * rendering can omit the manager and pass `:enable-row-selection=false`
 * to keep their column counts clean.
 */
function makeManager(
  tableId: string,
  enableRowSelection = false,
): ColumnManager {
  const colsRef = ref(buildColumns())
  return useColumnManager<Row>(tableId, colsRef, { enableRowSelection })
}

describe('DataTable', () => {
  beforeEach(() => {
    localStorage.clear()
    setContainerWidth(1440)
  })

  it('renders all visible columns in wide tier', async () => {
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-basic',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Ada')
    expect(wrapper.text()).toContain('Grace')
    expect(wrapper.findAll('thead th').length).toBe(3)
  })

  it('hides a column below its responsive breakpoint', async () => {
    setContainerWidth(800) // < lg (1024)
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-resp',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    const headers = wrapper.findAll('thead th').map((h) => h.text())
    expect(headers).not.toContain('City')
    expect(headers).toContain('Name')
    expect(headers).toContain('Age')
  })

  it('persists user column visibility toggles to localStorage', async () => {
    const manager = makeManager('test-persist')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-persist',
        manager,
      },
    })
    await flushPromises()
    manager.toggleColumn('age', false)
    await flushPromises()
    const stored = JSON.parse(localStorage.getItem('dt:test-persist:cols') ?? '{}')
    expect(stored).toEqual({ age: false })

    const headers = wrapper.findAll('thead th').map((h) => h.text())
    expect(headers).not.toContain('Age')
  })

  it('user override wins over container-width hint', async () => {
    setContainerWidth(800) // < lg, City hidden by hint
    const manager = makeManager('test-override')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-override',
        manager,
      },
    })
    await flushPromises()
    let headers = wrapper.findAll('thead th').map((h) => h.text())
    expect(headers).not.toContain('City')

    manager.toggleColumn('city', true)
    await flushPromises()
    headers = wrapper.findAll('thead th').map((h) => h.text())
    expect(headers).toContain('City')

    setContainerWidth(1440)
    await flushPromises()
    setContainerWidth(800)
    await flushPromises()
    headers = wrapper.findAll('thead th').map((h) => h.text())
    expect(headers).toContain('City')
  })

  it('emits row-click on row tap but not on action area', async () => {
    const onRowClick = vi.fn()
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-click',
        enableRowSelection: false,
        onRowClick,
      },
      slots: {
        'row-actions': (scope: { row: Row }) =>
          h('button', { class: 'action-btn' }, `act-${scope.row.id}`),
      },
    })
    await flushPromises()
    const firstNameCell = wrapper.findAll('tbody tr')[0].find('td:nth-child(1)')
    await firstNameCell.trigger('click')
    expect(onRowClick).toHaveBeenCalledTimes(1)

    onRowClick.mockClear()
    const actionBtn = wrapper.find('.action-btn')
    await actionBtn.trigger('click')
    expect(onRowClick).not.toHaveBeenCalled()
  })

  it('resets column overrides to defaults', async () => {
    const manager = makeManager('test-reset')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-reset',
        manager,
      },
    })
    await flushPromises()
    manager.toggleColumn('age', false)
    await flushPromises()
    expect(wrapper.findAll('thead th').map((h) => h.text())).not.toContain('Age')

    manager.resetAll()
    await flushPromises()
    expect(wrapper.findAll('thead th').map((h) => h.text())).toContain('Age')
    expect(localStorage.getItem('dt:test-reset:cols')).toBe('{}')
  })

  // ---- list tier (< 640 px container) ----------------------------------

  it('renders list tier when container is below 640 px', async () => {
    setContainerWidth(500)
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-list',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.findAll('ul.dt-list > li').length).toBe(3)
  })

  it('renders SortChip above list tier', async () => {
    setContainerWidth(500)
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-list-sort',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'SortChip' }).exists()).toBe(true)
  })

  it('list tier emits row-click on card tap', async () => {
    setContainerWidth(500)
    const onRowClick = vi.fn()
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-list-click',
        enableRowSelection: false,
        onRowClick,
      },
    })
    await flushPromises()
    const firstCard = wrapper.find('ul.dt-list > li')
    await firstCard.trigger('click')
    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(onRowClick.mock.calls[0]?.[0]).toMatchObject({ id: '1' })
  })

  it('list tier swaps to table tier when container grows', async () => {
    setContainerWidth(500)
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-list-grow',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    expect(wrapper.find('ul.dt-list').exists()).toBe(true)

    setContainerWidth(1440)
    await flushPromises()
    expect(wrapper.find('ul.dt-list').exists()).toBe(false)
    expect(wrapper.find('table').exists()).toBe(true)
  })

  it('table tier wrapper has no overflow utilities — page is the scrollport', async () => {
    // Per CSS Position L3, ANY non-`visible` overflow value (auto, scroll,
    // hidden, clip) makes the element a "scrollport" for sticky positioning,
    // which would trap the sticky thead INSIDE the wrapper instead of
    // letting it stick against the page scroll. The wrapper therefore must
    // have no overflow utilities at all.
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-scroll',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    const tableWrap = wrapper.find('table').element.parentElement!
    expect(tableWrap.className).not.toContain('overflow-auto')
    expect(tableWrap.className).not.toContain('overflow-x-auto')
    expect(tableWrap.className).not.toContain('overflow-y-auto')
    expect(tableWrap.className).not.toContain('overflow-x-clip')
    expect(tableWrap.className).not.toContain('overflow-y-clip')
    expect(tableWrap.className).not.toContain('overflow-hidden')
  })

  it('table tier wrapper carries `isolate` to encapsulate its z-stack', async () => {
    // Without isolation, the body's sticky-left pinned cells (z-10) tie with
    // any sibling page chrome at z-10 (the sticky FilterBar) and DOM order
    // breaks the tie WRONG — pinned cells paint over the FilterBar mid-scroll.
    // `isolation: isolate` confines the table's internal z-stack to the
    // wrapper so the page chrome's existing z-values cleanly outrank it.
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-isolate',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    const tableWrap = wrapper.find('table').element.parentElement!
    expect(tableWrap.className).toContain('isolate')
  })

  // ---- sticky context (header row + identifier column) ------------------

  it('thead is sticky and reads its top offset from --dt-thead-top', async () => {
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-sticky-thead',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    const thead = wrapper.find('thead')
    expect(thead.classes()).toContain('sticky')
    // Pages stack a sticky FilterBar above the table; they publish the bar's
    // height as `--dt-thead-top` (via ResizeObserver) so the thead lands
    // flush below. Default `0px` puts the thead at the page-scroll top
    // (which is right below the AppHeader) when no var is set.
    expect(
      thead.classes().some((c) => c.includes('dt-thead-top')),
    ).toBe(true)
  })

  it('auto-pins the identifier column to the left by default', async () => {
    const cols = buildColumns()
    cols[0].meta = { ...(cols[0].meta ?? {}), identifier: true } // mark `name`
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: cols,
        rows,
        tableId: 'test-auto-pin',
        enableRowSelection: false,
      },
    })
    await flushPromises()
    const nameHeader = wrapper
      .findAll('thead th')
      .find((th) => th.text().includes('Name'))!
    // No userPinning set, but the identifier flag drives the default pin.
    expect(nameHeader.attributes('data-pinned')).toBe('left')
  })

  it('user pin override disables the identifier auto-pin', async () => {
    const cols = buildColumns()
    cols[0].meta = { ...(cols[0].meta ?? {}), identifier: true } // `name`
    const colsRef = ref(cols)
    const manager = useColumnManager<Row>('test-pin-override', colsRef, {
      enableRowSelection: false,
    })
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: cols,
        rows,
        tableId: 'test-pin-override',
        manager,
      },
    })
    await flushPromises()
    // User explicitly pins a different column → defaults yield entirely.
    manager.togglePinColumn('age', 'left')
    await flushPromises()

    const nameHeader = wrapper
      .findAll('thead th')
      .find((th) => th.text().includes('Name'))!
    expect(nameHeader.attributes('data-pinned')).toBeUndefined()
    const ageHeader = wrapper
      .findAll('thead th')
      .find((th) => th.text().includes('Age'))!
    expect(ageHeader.attributes('data-pinned')).toBe('left')
  })

  // ---- column order ----------------------------------------------------

  it('persists column order via setColumnOrder', async () => {
    const manager = makeManager('test-order')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-order',
        manager,
      },
    })
    await flushPromises()

    manager.setColumnOrder(['age', 'name', 'city'])
    await flushPromises()

    const stored = JSON.parse(
      localStorage.getItem('dt:test-order:order') ?? '[]',
    )
    expect(stored).toEqual(['age', 'name', 'city'])

    void wrapper // mount kept alive to exercise the reactive path
  })

  it('reorder changes the on-screen column order', async () => {
    const manager = makeManager('test-order-dom')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-order-dom',
        manager,
      },
    })
    await flushPromises()

    manager.setColumnOrder(['age', 'name', 'city'])
    await flushPromises()

    const headers = wrapper.findAll('thead th').map((h) => h.text().trim())
    expect(headers[0]).toBe('Age')
    expect(headers[1]).toBe('Name')
  })

  // ---- column pinning --------------------------------------------------

  it('pins a column left and persists to localStorage', async () => {
    const manager = makeManager('test-pin-left')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-pin-left',
        manager,
      },
    })
    await flushPromises()

    manager.togglePinColumn('name', 'left')
    await flushPromises()

    const stored = JSON.parse(
      localStorage.getItem('dt:test-pin-left:pinning') ?? '{}',
    )
    expect(stored.left).toContain('name')
    expect(stored.right ?? []).not.toContain('name')

    const nameHeader = wrapper
      .findAll('thead th')
      .find((th) => th.text().includes('Name'))!
    expect(nameHeader.attributes('data-pinned')).toBe('left')
  })

  it('passing false to togglePinColumn unpins the column', async () => {
    const manager = makeManager('test-unpin')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-unpin',
        manager,
      },
    })
    await flushPromises()

    manager.togglePinColumn('name', 'left')
    await flushPromises()
    manager.togglePinColumn('name', false)
    await flushPromises()

    const stored = JSON.parse(
      localStorage.getItem('dt:test-unpin:pinning') ?? '{}',
    )
    expect(stored.left ?? []).not.toContain('name')
    expect(stored.right ?? []).toEqual([])

    void wrapper
  })

  // ---- reset -----------------------------------------------------------

  it('reset clears visibility, order, and pinning in one action', async () => {
    const manager = makeManager('test-reset-all')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-reset-all',
        manager,
      },
    })
    await flushPromises()

    manager.toggleColumn('age', false)
    manager.setColumnOrder(['city', 'age', 'name'])
    manager.togglePinColumn('name', 'left')
    await flushPromises()

    manager.resetAll()
    await flushPromises()

    expect(localStorage.getItem('dt:test-reset-all:cols')).toBe('{}')
    expect(localStorage.getItem('dt:test-reset-all:order')).toBe('[]')
    expect(
      JSON.parse(localStorage.getItem('dt:test-reset-all:pinning') ?? '{}'),
    ).toEqual({ left: [], right: [] })

    const headers = wrapper.findAll('thead th').map((h) => h.text().trim())
    expect(headers[0]).toBe('Name')
    expect(headers).toContain('Age')
  })

  // ---- native selection column injection -------------------------------

  it('injects a select column when the manager has enableRowSelection: true', async () => {
    const manager = makeManager('test-select-injected', /* enableRowSelection */ true)
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-select-injected',
        manager,
      },
    })
    await flushPromises()
    // 3 user columns + 1 injected select = 4
    expect(wrapper.findAll('thead th').length).toBe(4)
    // Header is the select-all checkbox; per-row cells are individual
    // checkboxes. We don't assert on Radix internals — just that a
    // checkbox-shaped element renders in the first column.
    const firstHeader = wrapper.findAll('thead th')[0]
    expect(firstHeader.find('button[role="checkbox"]').exists()).toBe(true)
    const firstBodyCell = wrapper
      .findAll('tbody tr')[0]
      .findAll('td')[0]
    expect(firstBodyCell.find('button[role="checkbox"]').exists()).toBe(true)
  })

  it('back-compat: when no manager prop, uses prop enableRowSelection (default true)', async () => {
    // No manager — useDataTable instantiates one internally with the
    // prop's enableRowSelection value (default true via withDefaults).
    // Confirms a future caller can use <DataTable> standalone without
    // hoisting and still get the historical selection-on default.
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-backcompat',
        // enableRowSelection not specified → defaults to true
      },
    })
    await flushPromises()
    expect(wrapper.findAll('thead th').length).toBe(4)
  })

  it('does not double-inject when caller already supplied a select column', async () => {
    // Defensive: caller-supplied 'select' column wins. Manager's
    // synthesis check skips, useDataTable's substitution check (header
    // present) skips. The caller's column shape passes through verbatim.
    const colsWithCallerSelect: DataTableColumnDef<Row>[] = [
      {
        id: 'select',
        meta: { alwaysVisible: true },
        header: () => h('span', { class: 'caller-header' }, 'CALLER'),
        cell: () => h('span', { class: 'caller-cell' }, 'X'),
      },
      ...buildColumns(),
    ]
    const colsRef = ref(colsWithCallerSelect)
    const manager = useColumnManager<Row>('test-caller-select', colsRef, {
      enableRowSelection: true,
    })
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: colsWithCallerSelect,
        rows,
        tableId: 'test-caller-select',
        manager,
      },
    })
    await flushPromises()
    expect(wrapper.findAll('thead th').length).toBe(4)
    expect(wrapper.find('.caller-header').exists()).toBe(true)
    expect(wrapper.findAll('.caller-cell').length).toBe(3)
  })

  it('header checkbox indeterminate when only some rows selected', async () => {
    const selection = ref<Record<string, boolean>>({ '1': true })
    const manager = makeManager('test-indeterminate', /* enableRowSelection */ true)
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-indeterminate',
        manager,
        rowSelection: selection.value,
      },
    })
    await flushPromises()
    const headerCheckbox = wrapper
      .findAll('thead th')[0]
      .find('button[role="checkbox"]')
    // Radix uses aria-checked='mixed' for indeterminate.
    expect(headerCheckbox.attributes('aria-checked')).toBe('mixed')
  })

  // ---- intent-vs-effective + indicator wiring -------------------------

  it('userVisibilityIntent stays all-true when responsiveHidden hides a column', async () => {
    // Mount the table at a narrow width that triggers ``responsiveHidden``
    // for the City column. The runtime layout adjustment must NOT bleed
    // into the form-binding state — the column-manager popover should
    // still see City as ✓ unless the user has toggled it off.
    setContainerWidth(800) // < lg (1024)
    const manager = makeManager('test-intent-narrow')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-intent-narrow',
        manager,
      },
    })
    await flushPromises()
    // Effective: City hidden by layout.
    expect(
      wrapper.findAll('thead th').map((h) => h.text()),
    ).not.toContain('City')
    // Intent: City still ✓ — the form should reflect "user hasn't filtered anything".
    expect(manager.userVisibilityIntent.value).toEqual({
      name: true,
      age: true,
      city: true,
    })
    expect(manager.hasUserHiddenColumns.value).toBe(false)
  })

  it('hasUserHiddenColumns lights when the user toggles a column off, dims when they re-enable', async () => {
    const manager = makeManager('test-indicator-toggle')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-indicator-toggle',
        manager,
      },
    })
    await flushPromises()
    expect(manager.hasUserHiddenColumns.value).toBe(false)

    manager.toggleColumn('age', false)
    await flushPromises()
    expect(manager.hasUserHiddenColumns.value).toBe(true)
    expect(
      wrapper.findAll('thead th').map((h) => h.text()),
    ).not.toContain('Age')

    manager.toggleColumn('age', true)
    await flushPromises()
    expect(manager.hasUserHiddenColumns.value).toBe(false)
    expect(
      wrapper.findAll('thead th').map((h) => h.text()),
    ).toContain('Age')
  })

  it('re-checking a responsively-hidden column writes explicit true and shows it at narrow width', async () => {
    setContainerWidth(800) // < lg, City hidden by hint
    const manager = makeManager('test-recheck-narrow')
    const wrapper = mount(DataTable<Row>, {
      props: {
        columns: buildColumns(),
        rows,
        tableId: 'test-recheck-narrow',
        manager,
      },
    })
    await flushPromises()
    expect(
      wrapper.findAll('thead th').map((h) => h.text()),
    ).not.toContain('City')

    // User explicitly checks it — the override beats the layout hint.
    manager.toggleColumn('city', true)
    await flushPromises()
    expect(
      wrapper.findAll('thead th').map((h) => h.text()),
    ).toContain('City')

    // Confirm the persisted intent is the explicit ``true`` (not absent).
    expect(manager.userVisibility.value.city).toBe(true)
    // The indicator stays off — re-enabling isn't "filtering active".
    expect(manager.hasUserHiddenColumns.value).toBe(false)
  })
})

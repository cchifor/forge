/**
 * Facade integration tests for ``useColumnManager``.
 *
 * The four single-responsibility sub-composables
 * (``useColumnVisibility``, ``useColumnOrder``, ``useColumnPinning``,
 * ``useColumnSizing``) own their own behaviour tests in their own
 * files. This file pins the facade contract:
 *
 *   - ``enableRowSelection`` synthesises the ``select`` descriptor and
 *     wires it through every sub-composable consistently
 *     (``augmentedColumns``, ``columnOrder``, ``columnPinning``).
 *   - ``setContainerWidth`` propagates to the visibility slice.
 *   - ``resetAll`` clears all four slices.
 *   - ``hasOverrides`` is the OR of the four sub-composable
 *     ``hasOverrides`` flags.
 *   - The new intent-vs-effective surface (``userVisibilityIntent``,
 *     ``hasUserHiddenColumns``) is reachable through the facade.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'

import { useColumnManager } from './useColumnManager'
import type { DataTableColumnDef } from './types'

interface Row {
  id: string
}

function makeColsNoSelect(): DataTableColumnDef<Row>[] {
  return [
    { id: 'name', accessorKey: 'name', cell: () => 'name' },
    { id: 'age', accessorKey: 'age', cell: () => 'age' },
  ]
}

describe('useColumnManager — enableRowSelection synthesis (facade integration)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('prepends a synthetic select descriptor when enableRowSelection is true', () => {
    // The page-level manager only sees user-defined columns; the actual
    // checkbox renderer is added by ``<DataTable>``. The manager
    // synthesises a descriptor so its ``columnOrder`` derivation lands
    // ``select`` at the front — without this, TanStack would render the
    // checkbox at the end of the row (because columns missing from
    // ``columnOrder`` are appended).
    const cols = ref(makeColsNoSelect())
    const mgr = useColumnManager<Row>('test-synth', cols, {
      enableRowSelection: true,
    })
    expect(mgr.augmentedColumns.value.map((c) => c.id)).toEqual([
      'select',
      'name',
      'age',
    ])
    expect(mgr.columnOrder.value).toEqual(['select', 'name', 'age'])
    expect(mgr.enableRowSelection).toBe(true)
  })

  it('does not synthesise when enableRowSelection is false (default)', () => {
    const cols = ref(makeColsNoSelect())
    const mgr = useColumnManager<Row>('test-no-synth', cols)
    expect(mgr.augmentedColumns.value.map((c) => c.id)).toEqual([
      'name',
      'age',
    ])
    expect(mgr.columnOrder.value).toEqual(['name', 'age'])
    expect(mgr.enableRowSelection).toBe(false)
  })

  it('does not synthesise when caller already declares a select column', () => {
    // Defensive: if a future caller hand-rolls a ``id: 'select'`` column,
    // we don't double-prepend. The caller's column wins.
    const cols = ref<DataTableColumnDef<Row>[]>([
      {
        id: 'select',
        meta: { alwaysVisible: true },
        cell: () => 'caller-select',
      },
      ...makeColsNoSelect(),
    ])
    const mgr = useColumnManager<Row>('test-caller-select', cols, {
      enableRowSelection: true,
    })
    expect(mgr.augmentedColumns.value.map((c) => c.id)).toEqual([
      'select',
      'name',
      'age',
    ])
    // Confirm we kept the caller's cell, didn't replace with synthetic.
    const selectCol = mgr.augmentedColumns.value.find((c) => c.id === 'select')
    expect(selectCol?.cell).toBeTypeOf('function')
  })

  it('places synthetic select at front of pinning derivation', () => {
    // Confirms the synthetic descriptor flows through to the pinning
    // sub-composable as an alwaysVisible column.
    const cols = ref(makeColsNoSelect())
    const mgr = useColumnManager<Row>('test-synth-pin', cols, {
      enableRowSelection: true,
    })
    expect(mgr.columnPinning.value.left[0]).toBe('select')
  })
})

describe('useColumnManager — setContainerWidth wires through to visibility', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('hides responsiveHidden columns when container narrows below threshold', () => {
    // ``setContainerWidth`` is the facade-level method; the visibility
    // sub-composable consumes the underlying ``containerWidth`` ref.
    // This test confirms the wiring rather than the visibility logic
    // itself (which is covered by useColumnVisibility.test.ts).
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'name', accessorKey: 'name', cell: () => 'name' },
      {
        id: 'extra',
        accessorKey: 'extra',
        meta: { responsiveHidden: { below: 'lg' } },
        cell: () => 'extra',
      },
    ])
    const mgr = useColumnManager<Row>('test-resp', cols)
    mgr.setContainerWidth(1200)
    expect(mgr.columnVisibility.value.extra).toBe(true)
    mgr.setContainerWidth(800)
    expect(mgr.columnVisibility.value.extra).toBe(false)
  })
})

describe('useColumnManager — facade aggregation', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('exposes userVisibilityIntent and hasUserHiddenColumns from the visibility slice', () => {
    const cols = ref(makeColsNoSelect())
    const mgr = useColumnManager<Row>('test-intent-aggr', cols)
    expect(mgr.userVisibilityIntent.value).toEqual({ name: true, age: true })
    expect(mgr.hasUserHiddenColumns.value).toBe(false)
    mgr.toggleColumn('age', false)
    expect(mgr.userVisibilityIntent.value.age).toBe(false)
    expect(mgr.hasUserHiddenColumns.value).toBe(true)
  })

  it('hasOverrides is the OR of all four sub-composable hasOverrides flags', () => {
    const cols = ref(makeColsNoSelect())
    const mgr = useColumnManager<Row>('test-or-overrides', cols)
    expect(mgr.hasOverrides.value).toBe(false)
    // Visibility override.
    mgr.toggleColumn('age', false)
    expect(mgr.hasOverrides.value).toBe(true)
    mgr.resetAll()
    expect(mgr.hasOverrides.value).toBe(false)
    // Order override.
    mgr.setColumnOrder(['age', 'name'])
    expect(mgr.hasOverrides.value).toBe(true)
    mgr.resetAll()
    expect(mgr.hasOverrides.value).toBe(false)
    // Pinning override.
    mgr.togglePinColumn('name', 'left')
    expect(mgr.hasOverrides.value).toBe(true)
    mgr.resetAll()
    expect(mgr.hasOverrides.value).toBe(false)
    // Sizing override.
    mgr.setColumnSizing({ name: 200 })
    expect(mgr.hasOverrides.value).toBe(true)
    mgr.resetAll()
    expect(mgr.hasOverrides.value).toBe(false)
  })

  it('resetAll clears every persistence key in one action', async () => {
    const cols = ref(makeColsNoSelect())
    const mgr = useColumnManager<Row>('test-reset-all', cols)
    mgr.toggleColumn('age', false)
    mgr.setColumnOrder(['age', 'name'])
    mgr.setColumnSizing({ name: 200 })
    mgr.togglePinColumn('name', 'left')
    await nextTick()
    expect(localStorage.getItem('dt:test-reset-all:cols')).not.toBe('{}')
    expect(localStorage.getItem('dt:test-reset-all:order')).not.toBe('[]')
    expect(localStorage.getItem('dt:test-reset-all:sizing')).not.toBe('{}')

    mgr.resetAll()
    await nextTick()
    expect(localStorage.getItem('dt:test-reset-all:cols')).toBe('{}')
    expect(localStorage.getItem('dt:test-reset-all:order')).toBe('[]')
    expect(localStorage.getItem('dt:test-reset-all:sizing')).toBe('{}')
    expect(
      JSON.parse(localStorage.getItem('dt:test-reset-all:pinning') ?? '{}'),
    ).toEqual({ left: [], right: [] })
  })

  it('togglableColumns excludes alwaysVisible columns and surfaces label/canResize/canPin', () => {
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'select', meta: { alwaysVisible: true }, cell: () => 'sel' },
      {
        id: 'name',
        accessorKey: 'name',
        header: 'Name',
        cell: () => 'name',
      },
      {
        id: 'age',
        accessorKey: 'age',
        header: 'Age',
        meta: { enableResizing: false, enablePinning: false },
        cell: () => 'age',
      },
    ])
    const mgr = useColumnManager<Row>('test-togglable', cols)
    expect(mgr.togglableColumns.value).toEqual([
      { id: 'name', label: 'Name', canResize: true, canPin: true },
      { id: 'age', label: 'Age', canResize: false, canPin: false },
    ])
  })
})

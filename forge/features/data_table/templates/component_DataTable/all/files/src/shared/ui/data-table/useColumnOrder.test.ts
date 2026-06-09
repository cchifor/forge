/**
 * Unit tests for ``useColumnOrder`` — the order slice extracted from
 * ``useColumnManager``. Migrates the four ``alwaysVisible``-anchor
 * regression tests (incident 2026-05-07) plus the stale-id and
 * forward-compat tests originally in ``useColumnManager.test.ts``.
 *
 * The contract pinned here: ``alwaysVisible`` columns lock at their
 * declared positions regardless of ``userOrder``, so reordering any
 * togglable column never silently moves the selection checkbox.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'

import { useColumnOrder } from './useColumnOrder'
import type { DataTableColumnDef } from './types'

interface Row {
  id: string
}

function makeCols(): DataTableColumnDef<Row>[] {
  return [
    {
      id: 'select',
      meta: { alwaysVisible: true },
      cell: () => 'sel',
    },
    { id: 'name', accessorKey: 'name', cell: () => 'name' },
    { id: 'age', accessorKey: 'age', cell: () => 'age' },
    { id: 'city', accessorKey: 'city', cell: () => 'city' },
  ]
}

describe('useColumnOrder', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns declared order when userOrder is empty', () => {
    const cols = ref(makeCols())
    const order = useColumnOrder('test-default', cols)
    expect(order.columnOrder.value).toEqual(['select', 'name', 'age', 'city'])
    expect(order.hasOverrides.value).toBe(false)
  })

  it('keeps alwaysVisible at column 0 when user has reordered togglable columns', () => {
    // Simulate: user opened the column-manager menu, dragged ``city``
    // before ``name``. Menu only sees togglable columns, so the
    // persisted userOrder is ``['city', 'name', 'age']`` — no
    // ``select`` because that's alwaysVisible and hidden from the
    // menu. The fix keeps ``select`` at its declared position.
    localStorage.setItem(
      'dt:test-reorder:order',
      JSON.stringify(['city', 'name', 'age']),
    )
    const cols = ref(makeCols())
    const order = useColumnOrder('test-reorder', cols)
    expect(order.columnOrder.value).toEqual(['select', 'city', 'name', 'age'])
    expect(order.hasOverrides.value).toBe(true)
  })

  it('keeps multiple alwaysVisible columns at their declared positions', () => {
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'select', meta: { alwaysVisible: true }, cell: () => 'sel' },
      { id: 'name', accessorKey: 'name', cell: () => 'name' },
      { id: 'age', accessorKey: 'age', cell: () => 'age' },
      {
        id: 'category',
        meta: { alwaysVisible: true, cardSubtitle: true },
        cell: () => 'cat',
      },
    ])
    localStorage.setItem(
      'dt:test-multi-anchor:order',
      JSON.stringify(['age', 'name']),
    )
    const order = useColumnOrder('test-multi-anchor', cols)
    expect(order.columnOrder.value).toEqual(['select', 'age', 'name', 'category'])
  })

  it('places newly-declared togglable columns after the user-ordered ones', () => {
    localStorage.setItem(
      'dt:test-new-col:order',
      JSON.stringify(['city', 'name']),
    )
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'select', meta: { alwaysVisible: true }, cell: () => 'sel' },
      { id: 'name', accessorKey: 'name', cell: () => 'name' },
      { id: 'age', accessorKey: 'age', cell: () => 'age' }, // not in userOrder yet
      { id: 'city', accessorKey: 'city', cell: () => 'city' },
    ])
    const order = useColumnOrder('test-new-col', cols)
    expect(order.columnOrder.value).toEqual(['select', 'city', 'name', 'age'])
  })

  it('drops stale userOrder entries that no longer exist in declared columns', () => {
    localStorage.setItem(
      'dt:test-stale:order',
      JSON.stringify(['removed_col', 'city', 'name']),
    )
    const cols = ref(makeCols())
    const order = useColumnOrder('test-stale', cols)
    expect(order.columnOrder.value).toEqual(['select', 'city', 'name', 'age'])
  })

  it('setColumnOrder writes to userOrder and persists to localStorage', async () => {
    const cols = ref(makeCols())
    const order = useColumnOrder('test-set', cols)
    order.setColumnOrder(['age', 'name', 'city'])
    expect(order.userOrder.value).toEqual(['age', 'name', 'city'])
    expect(order.hasOverrides.value).toBe(true)
    await nextTick()
    const stored = JSON.parse(
      localStorage.getItem('dt:test-set:order') ?? '[]',
    )
    expect(stored).toEqual(['age', 'name', 'city'])
  })

  it('reset clears userOrder and the storage entry', async () => {
    const cols = ref(makeCols())
    const order = useColumnOrder('test-reset', cols)
    order.setColumnOrder(['age', 'name'])
    order.reset()
    expect(order.userOrder.value).toEqual([])
    expect(order.hasOverrides.value).toBe(false)
    await nextTick()
    expect(localStorage.getItem('dt:test-reset:order')).toBe('[]')
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from './DataTable.vue'
import { effectScope, nextTick, ref, type EffectScope } from 'vue'
import { useDataTable } from './useDataTable'
import type { DataTableColumnDef } from './types'

type Item = { id: string; name: string; score: number }
const columns: DataTableColumnDef<Item>[] = [
  { accessorKey: 'name', header: 'Name', meta: { identifier: true } },
  { accessorKey: 'score', header: 'Score' },
]
const items: Item[] = [
  { id: 'b', name: 'Bravo', score: 2 },
  { id: 'a', name: 'Alpha', score: 1 },
]
const scopes: EffectScope[] = []
function create(options: Partial<Parameters<typeof useDataTable<Item>>[0]> = {}) {
  const scope = effectScope()
  scopes.push(scope)
  return scope.run(() => useDataTable<Item>({
    tableId: 'migration', columns, rows: ref([...items]), ...options,
  }))!
}
beforeEach(() => localStorage.clear())
afterEach(() => {
  scopes.splice(0).forEach(scope => scope.stop())
  vi.useRealTimers()
})

describe('DataTable v9 state and persisted preferences', () => {
  it('renders cell content and advances the pagination footer', async () => {
    const wrapper = mount(DataTable, {
      props: { tableId: 'render', rows: items, columns, mode: 'pagination', pageSize: 1, enableRowSelection: false },
    })
    try {
      expect(wrapper.text()).toContain('Bravo')
      expect(wrapper.text()).toContain('Page 1 of 2')
      const next = wrapper.findAll('button').find(button => button.attributes('aria-label') === 'Next page')!
      await next.trigger('click')
      expect(wrapper.text()).toContain('Alpha')
      expect(wrapper.text()).toContain('Page 2 of 2')
    } finally {
      wrapper.unmount()
    }
  })

  it('sorts reactively and applies debounced global filters', async () => {
    vi.useFakeTimers()
    const rows = ref([...items])
    const globalFilter = ref('')
    const { table } = create({ rows, globalFilter })
    table.getColumn('name')!.toggleSorting(false)
    await nextTick()
    expect(table.getRowModel().rows.map(row => row.id)).toEqual(['a', 'b'])
    rows.value = [...items, { id: 'c', name: 'Charlie', score: 3 }]
    await nextTick()
    expect(table.getRowModel().rows.map(row => row.id)).toEqual(['a', 'b', 'c'])
    globalFilter.value = 'Bravo'
    await nextTick()
    await vi.advanceTimersByTimeAsync(181)
    await nextTick()
    expect(table.getRowModel().rows.map(row => row.id)).toEqual(['b'])
  })

  it('paginates and synchronizes externally controlled row selection', async () => {
    const selection = ref<Record<string, boolean>>({})
    const onSelectionChange = vi.fn()
    const { table } = create({ pageSize: 1, selection, onSelectionChange })
    expect(table.getPageCount()).toBe(2)
    expect(table.getRowModel().rows.map(row => row.id)).toEqual(['b'])
    table.nextPage()
    await nextTick()
    expect(table.atoms.pagination.get().pageIndex).toBe(1)
    expect(table.getRowModel().rows.map(row => row.id)).toEqual(['a'])
    table.getRowModel().rows[0]!.toggleSelected(true)
    await nextTick()
    expect(selection.value).toEqual({ a: true })
    expect(onSelectionChange).toHaveBeenLastCalledWith({ a: true })
  })

  it('preserves left/right storage while adapting logical start/end pinning', async () => {
    localStorage.setItem('dt:migration:pinning', JSON.stringify({ left: ['score'], right: ['old'] }))
    const first = create()
    expect(first.manager.columnPinning.value).toEqual({ left: ['select', 'score'], right: [] })
    expect(first.table.atoms.columnPinning.get()).toEqual({ start: ['select', 'score'], end: [] })
    expect(first.table.getColumn('score')!.getIsPinned()).toBe('start')
    first.table.getColumn('name')!.pin('start')
    await nextTick()
    const stored = JSON.parse(localStorage.getItem('dt:migration:pinning')!)
    expect(stored.left).toEqual(['select', 'score', 'name'])
    expect(stored.right).toEqual([])
    expect(stored).not.toHaveProperty('start')
    scopes.splice(0).forEach(scope => scope.stop())
    const restored = create()
    expect(restored.table.atoms.columnPinning.get().start).toEqual(['select', 'score', 'name'])
    restored.manager.resetAll()
    await nextTick()
    expect(restored.table.atoms.columnPinning.get().start).toEqual(['select', 'name'])
  })

  it('keeps hidden-column preferences across table instances', async () => {
    const first = create()
    first.manager.toggleColumn('score', false)
    await nextTick()
    expect(first.table.getVisibleLeafColumns().map(column => column.id)).toEqual(['select', 'name'])
    scopes.splice(0).forEach(scope => scope.stop())
    const restored = create()
    expect(restored.table.getColumn('score')!.getIsVisible()).toBe(false)
    restored.manager.resetAll()
    await nextTick()
    expect(restored.table.getColumn('score')!.getIsVisible()).toBe(true)
  })
})

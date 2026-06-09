/**
 * Unit tests for ``useColumnPinning`` — the pinning slice extracted
 * from ``useColumnManager``. Migrates the pinning regression tests
 * (incident 2026-05-07, PR #90) plus the legacy-right-pin drop test
 * originally in ``useColumnManager.test.ts``.
 *
 * The contracts pinned here:
 *   - ``alwaysVisible`` columns lock at the FRONT of the left-pinned
 *     list (TanStack renders pinned-left BEFORE non-pinned regardless
 *     of ``columnOrder``, so without this the selection checkbox would
 *     drop behind any user-pinned column).
 *   - ``identifier`` columns auto-pin to the left when no user pinning
 *     is set, so the row's identity stays anchored while scrolling
 *     right. The first user pin disables the auto-derivation.
 *   - Right-side pinning is silently dropped on derivation
 *     (removed end-to-end in PR #88 but the storage shape still
 *     carries ``right: []`` for TanStack compat).
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'

import { useColumnPinning } from './useColumnPinning'
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

describe('useColumnPinning', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('auto-pins alwaysVisible + identifier columns when no user pinning', () => {
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'select', meta: { alwaysVisible: true }, cell: () => 'sel' },
      {
        id: 'name',
        accessorKey: 'name',
        meta: { identifier: true },
        cell: () => 'name',
      },
      { id: 'age', accessorKey: 'age', cell: () => 'age' },
    ])
    const pinning = useColumnPinning('test-default-pin', cols)
    expect(pinning.columnPinning.value).toEqual({
      left: ['select', 'name'],
      right: [],
    })
    expect(pinning.hasOverrides.value).toBe(false)
  })

  it('keeps alwaysVisible at the FRONT of left-pin even when user pins another column', () => {
    localStorage.setItem(
      'dt:test-user-pin:pinning',
      JSON.stringify({ left: ['name'], right: [] }),
    )
    const cols = ref(makeCols())
    const pinning = useColumnPinning('test-user-pin', cols)
    expect(pinning.columnPinning.value.left).toEqual(['select', 'name'])
    expect(pinning.columnPinning.value.right).toEqual([])
    expect(pinning.hasOverrides.value).toBe(true)
  })

  it('silently drops legacy right-pin entries from persisted state', () => {
    localStorage.setItem(
      'dt:test-legacy-right:pinning',
      JSON.stringify({ left: [], right: ['city'] }),
    )
    const cols = ref(makeCols())
    const pinning = useColumnPinning('test-legacy-right', cols)
    // No user-left, so the auto-pin path runs: alwaysVisible only
    // (no identifier in makeCols()).
    expect(pinning.columnPinning.value.left).toEqual(['select'])
    expect(pinning.columnPinning.value.right).toEqual([])
  })

  it('deduplicates if user storage somehow contains an alwaysVisible column', () => {
    // Defensive: if ``userPinning.left`` ever contains an
    // alwaysVisible ID (e.g. via storage corruption, or a future
    // migration), don't double-render it. The alwaysVisible prefix
    // takes precedence; the duplicate entry is filtered out.
    localStorage.setItem(
      'dt:test-dedup:pinning',
      JSON.stringify({ left: ['select', 'name'], right: [] }),
    )
    const cols = ref(makeCols())
    const pinning = useColumnPinning('test-dedup', cols)
    expect(pinning.columnPinning.value.left).toEqual(['select', 'name'])
    expect(pinning.columnPinning.value.right).toEqual([])
  })

  it('togglePinColumn(left) adds the id to userPinning.left and persists', async () => {
    const cols = ref(makeCols())
    const pinning = useColumnPinning('test-toggle-on', cols)
    pinning.togglePinColumn('name', 'left')
    expect(pinning.userPinning.value.left).toContain('name')
    expect(pinning.columnPinning.value.left).toEqual(['select', 'name'])
    await nextTick()
    const stored = JSON.parse(
      localStorage.getItem('dt:test-toggle-on:pinning') ?? '{}',
    )
    expect(stored.left).toEqual(['name'])
    expect(stored.right).toEqual([])
  })

  it('togglePinColumn(false) removes the id from userPinning.left', async () => {
    const cols = ref(makeCols())
    const pinning = useColumnPinning('test-toggle-off', cols)
    pinning.togglePinColumn('name', 'left')
    pinning.togglePinColumn('name', false)
    expect(pinning.userPinning.value.left).not.toContain('name')
    await nextTick()
    const stored = JSON.parse(
      localStorage.getItem('dt:test-toggle-off:pinning') ?? '{}',
    )
    expect(stored.left).toEqual([])
  })

  it('reset clears userPinning to empty left+right', async () => {
    const cols = ref(makeCols())
    const pinning = useColumnPinning('test-reset', cols)
    pinning.togglePinColumn('name', 'left')
    pinning.reset()
    expect(pinning.userPinning.value).toEqual({ left: [], right: [] })
    expect(pinning.hasOverrides.value).toBe(false)
    await nextTick()
    const stored = JSON.parse(
      localStorage.getItem('dt:test-reset:pinning') ?? '{}',
    )
    expect(stored).toEqual({ left: [], right: [] })
  })
})

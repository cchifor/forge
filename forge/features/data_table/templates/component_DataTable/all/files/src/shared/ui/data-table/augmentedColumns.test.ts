/**
 * Unit tests for ``useAugmentedColumns`` — the helper that prepends a
 * synthetic ``select`` descriptor when ``enableRowSelection`` is true.
 * Extracted out of ``useColumnManager`` so all four sub-composables
 * (visibility, order, pinning, sizing) consume the same column list.
 */
import { describe, it, expect } from 'vitest'
import { ref } from 'vue'

import { useAugmentedColumns } from './augmentedColumns'
import type { DataTableColumnDef } from './types'

interface Row {
  id: string
}

function makeUserCols(): DataTableColumnDef<Row>[] {
  return [
    { id: 'name', accessorKey: 'name', cell: () => 'name' },
    { id: 'age', accessorKey: 'age', cell: () => 'age' },
  ]
}

describe('useAugmentedColumns', () => {
  it('returns the user columns unchanged when enableRowSelection is false', () => {
    const cols = ref(makeUserCols())
    const augmented = useAugmentedColumns(cols, false)
    expect(augmented.value.map((c) => c.id)).toEqual(['name', 'age'])
  })

  it('prepends a synthetic select descriptor when enableRowSelection is true', () => {
    const cols = ref(makeUserCols())
    const augmented = useAugmentedColumns(cols, true)
    expect(augmented.value.map((c) => c.id)).toEqual(['select', 'name', 'age'])
    const select = augmented.value[0]
    expect(select.meta?.alwaysVisible).toBe(true)
    expect(select.meta?.enableResizing).toBe(false)
    expect(select.meta?.enablePinning).toBe(false)
  })

  it('does not double-prepend when caller already declares a select column', () => {
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'select', meta: { alwaysVisible: true }, cell: () => 'caller' },
      ...makeUserCols(),
    ])
    const augmented = useAugmentedColumns(cols, true)
    expect(augmented.value.map((c) => c.id)).toEqual(['select', 'name', 'age'])
    expect(augmented.value[0].cell).toBeTypeOf('function')
  })

  it('reacts when the source columns ref changes', () => {
    const cols = ref(makeUserCols())
    const augmented = useAugmentedColumns(cols, true)
    expect(augmented.value.map((c) => c.id)).toEqual(['select', 'name', 'age'])
    cols.value = [
      { id: 'city', accessorKey: 'city', cell: () => 'city' },
    ]
    expect(augmented.value.map((c) => c.id)).toEqual(['select', 'city'])
  })

  it('also detects a caller select column referenced by accessorKey', () => {
    const cols = ref<DataTableColumnDef<Row>[]>([
      // No explicit ``id``; the helper must fall back to ``accessorKey``
      // when checking for an existing select column. (Used by the
      // legacy code path; keeping the contract for safety.)
      { accessorKey: 'select', cell: () => 'caller' } as DataTableColumnDef<Row>,
      ...makeUserCols(),
    ])
    const augmented = useAugmentedColumns(cols, true)
    expect(augmented.value).toHaveLength(3)
    expect(augmented.value.map((c) => c.id ?? (c as { accessorKey?: string }).accessorKey)).toEqual([
      'select',
      'name',
      'age',
    ])
  })
})

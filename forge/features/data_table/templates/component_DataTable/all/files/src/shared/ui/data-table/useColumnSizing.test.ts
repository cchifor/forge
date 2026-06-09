/**
 * Unit tests for ``useColumnSizing`` — the sizing slice extracted from
 * ``useColumnManager``. Sizing is a passthrough today: there's no
 * derivation logic, just persisted user-set widths keyed by column id.
 * These tests pin the contract so the facade can compose it without
 * replicating the storage shape.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { nextTick } from 'vue'

import { useColumnSizing } from './useColumnSizing'

describe('useColumnSizing', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts with empty sizing and no overrides', () => {
    const sizing = useColumnSizing('test-empty')
    expect(sizing.columnSizing.value).toEqual({})
    expect(sizing.userSizing.value).toEqual({})
    expect(sizing.hasOverrides.value).toBe(false)
  })

  it('writes column widths via setColumnSizing and persists to localStorage', async () => {
    const sizing = useColumnSizing('test-set')
    sizing.setColumnSizing({ name: 240, age: 80 })
    expect(sizing.columnSizing.value).toEqual({ name: 240, age: 80 })
    expect(sizing.hasOverrides.value).toBe(true)
    // useStorage syncs on next microtask via its watcher.
    await nextTick()
    const stored = JSON.parse(
      localStorage.getItem('dt:test-set:sizing') ?? '{}',
    )
    expect(stored).toEqual({ name: 240, age: 80 })
  })

  it('rehydrates from localStorage on construction', () => {
    localStorage.setItem(
      'dt:test-rehydrate:sizing',
      JSON.stringify({ city: 160 }),
    )
    const sizing = useColumnSizing('test-rehydrate')
    expect(sizing.columnSizing.value).toEqual({ city: 160 })
    expect(sizing.hasOverrides.value).toBe(true)
  })

  it('reset clears the sizing map and the storage entry', async () => {
    const sizing = useColumnSizing('test-reset')
    sizing.setColumnSizing({ name: 200 })
    sizing.reset()
    expect(sizing.columnSizing.value).toEqual({})
    expect(sizing.hasOverrides.value).toBe(false)
    await nextTick()
    expect(localStorage.getItem('dt:test-reset:sizing')).toBe('{}')
  })

  it('uses a per-tableId storage key so multiple tables do not collide', () => {
    const a = useColumnSizing('table-a')
    const b = useColumnSizing('table-b')
    a.setColumnSizing({ name: 100 })
    b.setColumnSizing({ name: 999 })
    expect(a.columnSizing.value).toEqual({ name: 100 })
    expect(b.columnSizing.value).toEqual({ name: 999 })
  })
})

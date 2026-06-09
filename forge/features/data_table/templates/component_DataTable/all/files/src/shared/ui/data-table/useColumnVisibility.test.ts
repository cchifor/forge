/**
 * Unit tests for ``useColumnVisibility`` — the visibility slice
 * extracted from ``useColumnManager`` and extended with the new
 * intent-vs-effective split.
 *
 * Three-state semantics pinned here:
 *   - Form intent (``userVisibilityIntent``) — defaults to ✓ for every
 *     togglable column. Reflects user toggles only. The popover binds
 *     to this.
 *   - Effective (``columnVisibility``) — what TanStack consumes. Merge:
 *     user override > responsive layout hint > shown.
 *   - Indicator (``hasUserHiddenColumns``) — true iff any column has
 *     been explicitly hidden by the user (any ``userVisibility[id]
 *     === false``). Drives the column-manager trigger-button dot.
 *
 * The form and effective state can disagree when ``responsiveHidden``
 * kicks in at narrow container widths — by design (option A from the
 * brainstorming session), so the form always reflects user intent and
 * the runtime layout adjustment is invisible to the menu.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'

import { useColumnVisibility } from './useColumnVisibility'
import type { DataTableColumnDef } from './types'

interface Row {
  id: string
}

function makeBasicCols(): DataTableColumnDef<Row>[] {
  return [
    { id: 'name', accessorKey: 'name', cell: () => 'name' },
    { id: 'age', accessorKey: 'age', cell: () => 'age' },
    { id: 'city', accessorKey: 'city', cell: () => 'city' },
  ]
}

describe('useColumnVisibility — defaults', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts with empty userVisibility, intent all-true, effective all-true', () => {
    const cols = ref(makeBasicCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-default', cols, {
      containerWidth,
    })
    expect(visibility.userVisibility.value).toEqual({})
    expect(visibility.userVisibilityIntent.value).toEqual({
      name: true,
      age: true,
      city: true,
    })
    expect(visibility.columnVisibility.value).toEqual({
      name: true,
      age: true,
      city: true,
    })
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
    expect(visibility.hasOverrides.value).toBe(false)
  })

  it('alwaysVisible columns are excluded from the intent map', () => {
    const cols = ref<DataTableColumnDef<Row>[]>([
      { id: 'select', meta: { alwaysVisible: true }, cell: () => 'sel' },
      ...makeBasicCols(),
    ])
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-always', cols, {
      containerWidth,
    })
    // alwaysVisible columns aren't user-controllable; the intent map
    // only covers togglable columns.
    expect(visibility.userVisibilityIntent.value).toEqual({
      name: true,
      age: true,
      city: true,
    })
    // Effective state still includes alwaysVisible (always shown).
    expect(visibility.columnVisibility.value.select).toBe(true)
  })
})

describe('useColumnVisibility — toggleColumn writes explicit values', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('toggleColumn(false) hides effective and lights the indicator', () => {
    const cols = ref(makeBasicCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-hide', cols, {
      containerWidth,
    })
    visibility.toggleColumn('age', false)
    expect(visibility.userVisibility.value.age).toBe(false)
    expect(visibility.userVisibilityIntent.value.age).toBe(false)
    expect(visibility.columnVisibility.value.age).toBe(false)
    expect(visibility.hasUserHiddenColumns.value).toBe(true)
    expect(visibility.hasOverrides.value).toBe(true)
  })

  it('toggleColumn(true) writes explicit true (not delete) so it overrides any layout hint', () => {
    const cols = ref(makeBasicCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-show', cols, {
      containerWidth,
    })
    visibility.toggleColumn('age', false)
    visibility.toggleColumn('age', true)
    // Explicit true, not absent — re-checking a responsively-hidden
    // column needs to override the layout hint, which only works when
    // the value is explicitly stored.
    expect(visibility.userVisibility.value.age).toBe(true)
    expect(visibility.userVisibilityIntent.value.age).toBe(true)
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
    expect(visibility.hasOverrides.value).toBe(true)
  })

  it('hasUserHiddenColumns lights only when any explicit false exists', () => {
    const cols = ref(makeBasicCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-indicator', cols, {
      containerWidth,
    })
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
    visibility.toggleColumn('age', true) // explicit true
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
    visibility.toggleColumn('age', false) // explicit false
    expect(visibility.hasUserHiddenColumns.value).toBe(true)
    visibility.toggleColumn('age', true) // back to true
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
  })

  it('persists toggles to localStorage', async () => {
    const cols = ref(makeBasicCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-persist', cols, {
      containerWidth,
    })
    visibility.toggleColumn('age', false)
    await nextTick()
    const stored = JSON.parse(
      localStorage.getItem('dt:test-persist:cols') ?? '{}',
    )
    expect(stored).toEqual({ age: false })
  })
})

describe('useColumnVisibility — responsiveHidden interaction', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  function makeRespCols(): DataTableColumnDef<Row>[] {
    return [
      { id: 'name', accessorKey: 'name', cell: () => 'name' },
      {
        id: 'extra',
        accessorKey: 'extra',
        meta: { responsiveHidden: { below: 'lg' } },
        cell: () => 'extra',
      },
    ]
  }

  it('intent stays ✓ at narrow width while effective is hidden by layout', () => {
    const cols = ref(makeRespCols())
    const containerWidth = ref(800) // < lg=1024
    const visibility = useColumnVisibility('test-narrow', cols, {
      containerWidth,
    })
    // Form: I haven't unchecked anything → intent shows it as on.
    expect(visibility.userVisibilityIntent.value.extra).toBe(true)
    // Table: layout hides it because the container is narrow.
    expect(visibility.columnVisibility.value.extra).toBe(false)
    // Indicator: the user hasn't filtered anything; layout adjusted.
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
  })

  it('re-checking a responsively-hidden column shows it (override wins)', () => {
    const cols = ref(makeRespCols())
    const containerWidth = ref(800)
    const visibility = useColumnVisibility('test-override', cols, {
      containerWidth,
    })
    // Initial: hidden by layout, intent says shown.
    expect(visibility.columnVisibility.value.extra).toBe(false)
    // User explicitly checks it (writes explicit true).
    visibility.toggleColumn('extra', true)
    // Override wins — column is shown despite the narrow container.
    expect(visibility.columnVisibility.value.extra).toBe(true)
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
  })

  it('reacts to container width changes', () => {
    const cols = ref(makeRespCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-resize', cols, {
      containerWidth,
    })
    expect(visibility.columnVisibility.value.extra).toBe(true)
    containerWidth.value = 800
    expect(visibility.columnVisibility.value.extra).toBe(false)
    containerWidth.value = 1440
    expect(visibility.columnVisibility.value.extra).toBe(true)
  })
})

describe('useColumnVisibility — cardSubtitle list-tier-only', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  function makeColsWithSubtitle(): DataTableColumnDef<Row>[] {
    return [
      { id: 'name', accessorKey: 'name', cell: () => 'name' },
      {
        id: 'category',
        meta: { cardSubtitle: true, alwaysVisible: true },
        cell: () => 'cat',
      },
    ]
  }

  it('cardSubtitle column is hidden in non-list tier', () => {
    const cols = ref(makeColsWithSubtitle())
    const containerWidth = ref(1440) // wide tier
    const visibility = useColumnVisibility('test-subtitle-wide', cols, {
      containerWidth,
    })
    expect(visibility.columnVisibility.value.category).toBe(false)
  })

  it('cardSubtitle column is shown in list tier', () => {
    const cols = ref(makeColsWithSubtitle())
    const containerWidth = ref(500) // < sm=640
    const visibility = useColumnVisibility('test-subtitle-list', cols, {
      containerWidth,
    })
    expect(visibility.columnVisibility.value.category).toBe(true)
  })
})

describe('useColumnVisibility — reset', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('reset clears userVisibility and turns the indicator off', async () => {
    const cols = ref(makeBasicCols())
    const containerWidth = ref(1440)
    const visibility = useColumnVisibility('test-reset', cols, {
      containerWidth,
    })
    visibility.toggleColumn('age', false)
    expect(visibility.hasUserHiddenColumns.value).toBe(true)
    visibility.reset()
    expect(visibility.userVisibility.value).toEqual({})
    expect(visibility.userVisibilityIntent.value).toEqual({
      name: true,
      age: true,
      city: true,
    })
    expect(visibility.hasUserHiddenColumns.value).toBe(false)
    expect(visibility.hasOverrides.value).toBe(false)
    await nextTick()
    expect(localStorage.getItem('dt:test-reset:cols')).toBe('{}')
  })
})

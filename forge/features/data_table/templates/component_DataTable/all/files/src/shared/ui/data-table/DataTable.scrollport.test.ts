/**
 * Single-scrollport invariant for ``<DataTable>``.
 *
 * The shared table is designed so the **page** is the only vertical
 * scrollport — `<main> > div.overflow-auto` in MainLayout. Adding a
 * sub-scroll container inside the table breaks two things at once:
 *
 *   1. The user sees a second vertical scrollbar nested inside the
 *      page scrollbar, with the wrong key behaviour (Page Down moves
 *      the page, not the table). This is the regression report
 *      logged on 2026-05-06 against PR #68.
 *   2. ``position: sticky`` on ``<thead>`` resolves against the
 *      nearest scrolling ancestor. If that ancestor is the table
 *      wrapper instead of ``<main> > div.overflow-auto``, the
 *      thead's ``top: var(--dt-thead-top)`` calibration loses its
 *      anchor — column headers stop sticking under the FilterBar
 *      and instead stick to the top of the table itself.
 *
 * What this test pins
 * -------------------
 * For every layout tier (list / compact / wide), no element under
 * ``.dt-root`` may have a computed ``overflow-x`` or ``overflow-y``
 * of ``auto`` or ``scroll``. The only allowed values are ``visible``,
 * ``hidden``, and ``clip`` — none of which produce a scrollbar.
 *
 * jsdom returns *declared* styles via ``getComputedStyle``; it does
 * not run the layout engine. That's enough to catch the failure
 * mode we care about, which is "someone added an `overflow-y: auto`
 * Tailwind utility to the wrapper" — the exact shape every prior
 * regression has taken (see git history of DataTable.vue: the
 * `overflow-x-clip` → `overflow-auto` swap in 3d2dd37 had to be
 * reverted in 104a2ec for this same reason).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h } from 'vue'

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
import type { DataTableColumnDef } from './types'

const mockWidth = (
  ContainerSizeMock as unknown as { __mockWidth: { value: number } }
).__mockWidth

interface Row {
  id: string
  name: string
  status: string
  notes: string
}

const rows: Row[] = [
  { id: '1', name: 'Ada', status: 'active', notes: 'short' },
  { id: '2', name: 'Grace', status: 'paused', notes: 'a much longer note that would tempt a row to grow a sub-scroller' },
  { id: '3', name: 'Alan', status: 'active', notes: '—' },
]

function columns(): DataTableColumnDef<Row>[] {
  return [
    {
      id: 'name',
      accessorKey: 'name',
      header: 'Name',
      meta: { cardHero: true, identifier: true },
      cell: ({ row }) => h('span', row.original.name),
    },
    {
      id: 'status',
      accessorKey: 'status',
      header: 'Status',
      cell: ({ row }) => h('span', row.original.status),
    },
    {
      id: 'notes',
      accessorKey: 'notes',
      header: 'Notes',
      cell: ({ row }) => h('span', row.original.notes),
    },
  ]
}

const SCROLLABLE_OVERFLOW = new Set(['auto', 'scroll', 'overlay'])

// Tailwind utilities that produce a scrolling container. jsdom does
// not process the project's Tailwind stylesheet, so ``getComputedStyle``
// won't see ``overflow-y-auto`` applied via class. Lint the class
// strings directly to cover that gap. Inline styles are still caught
// by the ``getComputedStyle`` walk above.
const OVERFLOW_CLASS_PATTERNS = [
  /(^|\s)overflow-(auto|scroll|overlay)(\s|$)/,
  /(^|\s)overflow-x-(auto|scroll|overlay)(\s|$)/,
  /(^|\s)overflow-y-(auto|scroll|overlay)(\s|$)/,
]

function offendingDescendants(root: HTMLElement): Array<{
  el: HTMLElement
  via: 'computed' | 'class'
  detail: string
  className: string
}> {
  const offenders: Array<{
    el: HTMLElement
    via: 'computed' | 'class'
    detail: string
    className: string
  }> = []
  const all = [root, ...Array.from(root.querySelectorAll<HTMLElement>('*'))]
  for (const el of all) {
    const cs = window.getComputedStyle(el)
    if (SCROLLABLE_OVERFLOW.has(cs.overflowX)) {
      offenders.push({
        el,
        via: 'computed',
        detail: `overflow-x: ${cs.overflowX}`,
        className: el.className,
      })
    }
    if (SCROLLABLE_OVERFLOW.has(cs.overflowY)) {
      offenders.push({
        el,
        via: 'computed',
        detail: `overflow-y: ${cs.overflowY}`,
        className: el.className,
      })
    }
    const cls = String(el.className || '')
    for (const pattern of OVERFLOW_CLASS_PATTERNS) {
      const match = pattern.exec(cls)
      if (match) {
        offenders.push({
          el,
          via: 'class',
          detail: `Tailwind utility: ${match[0].trim()}`,
          className: cls,
        })
        break
      }
    }
  }
  return offenders
}

function describeOffenders(
  offenders: ReturnType<typeof offendingDescendants>,
): string {
  return offenders
    .map(
      (o) =>
        `  [${o.via}] <${o.el.tagName.toLowerCase()} class="${o.className}"> — ${o.detail}`,
    )
    .join('\n')
}

describe('DataTable scrollport invariant', () => {
  beforeEach(() => {
    localStorage.clear()
    mockWidth.value = 1440
  })

  it.each([
    { tier: 'wide', width: 1440 },
    { tier: 'compact', width: 800 },
    { tier: 'list', width: 480 },
  ])(
    'no element under .dt-root has overflow-x/y in {auto, scroll} ($tier tier @ ${width}px)',
    async ({ width }) => {
      mockWidth.value = width
      const wrapper = mount(DataTable<Row>, {
        attachTo: document.body,
        props: {
          columns: columns(),
          rows,
          tableId: `test-scrollport-${width}`,
        },
      })
      await flushPromises()

      const root = wrapper.find<HTMLElement>('.dt-root').element
      const offenders = offendingDescendants(root)

      expect(
        offenders.length,
        `expected zero scrolling utilities under .dt-root, got ${offenders.length}:\n${describeOffenders(offenders)}\n` +
          'The table wrapper (and every descendant) must let the page handle scrolling. ' +
          'See DataTable.vue lines 525-534 for the architectural note. If you need to ' +
          'truncate cell text use overflow: hidden + text-overflow: ellipsis, never auto/scroll.',
      ).toBe(0)

      wrapper.unmount()
    },
  )
})

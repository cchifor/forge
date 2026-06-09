/**
 * Component tests for ``<ColumnManagerMenu>`` — the popover that
 * exposes per-column visibility, drag-reorder, and pin-toggle controls
 * in the page's FilterBar.
 *
 * Three behaviours pinned here:
 *
 *   1. Checkboxes bind to the new ``intent`` prop (the form-binding
 *      state from ``useColumnVisibility``), defaulting to ✓ regardless
 *      of the underlying effective visibility.
 *   2. The trigger button shows an indicator dot iff the
 *      ``hasHiddenColumns`` prop is true. ``aria-label`` flips along
 *      with the dot so screen readers announce the filtered state.
 *   3. The pin control is a single-click toggle (no DropdownMenu);
 *      ``<Pin>`` ↔ ``<PinOff>`` glyph swap reads as "click to pin"
 *      and "click to unpin" respectively.
 *
 * Reorder is wired to native HTML5 drag-and-drop (no vue-draggable-plus
 * dependency). Native DnD is unreliable in jsdom, so the reorder contract
 * is asserted two ways: (a) the ``order`` prop drives the rendered row
 * order, and (b) dispatching native drag events through the row container
 * emits ``reorder`` with the reordered id list.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'

import ColumnManagerMenu, {
  type ColumnManagerColumn,
} from './ColumnManagerMenu.vue'

const columns: ColumnManagerColumn[] = [
  { id: 'name', label: 'Name', canResize: true, canPin: true },
  { id: 'age', label: 'Age', canResize: true, canPin: true },
  { id: 'city', label: 'City', canResize: true, canPin: true },
]

function emptyIntent(): Record<string, boolean> {
  return { name: true, age: true, city: true }
}

function emptyPinning(): { left: string[]; right: string[] } {
  return { left: [], right: [] }
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('ColumnManagerMenu — trigger indicator dot', () => {
  it('shows no indicator dot when hasHiddenColumns is false', () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
      },
    })
    expect(
      wrapper.find('[data-testid="column-manager-filter-indicator"]').exists(),
    ).toBe(false)
    const trigger = wrapper.find('button[aria-label]')
    expect(trigger.attributes('aria-label')).toBe('Manage columns')
  })

  it('shows the indicator dot and updates aria-label when hasHiddenColumns is true', () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: { ...emptyIntent(), age: false },
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: true,
        hasHiddenColumns: true,
      },
    })
    expect(
      wrapper.find('[data-testid="column-manager-filter-indicator"]').exists(),
    ).toBe(true)
    const trigger = wrapper.find('button[aria-label]')
    expect(trigger.attributes('aria-label')).toBe(
      'Manage columns, filtering active',
    )
  })
})

describe('ColumnManagerMenu — popover content', () => {
  it('renders one checkbox per togglable column, all checked when intent is all-true', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
        // Open the popover on mount so its content renders into a portal.
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    // PopoverContent teleports to document.body.
    const checkboxes = document.body.querySelectorAll(
      'button[role="checkbox"]',
    )
    expect(checkboxes.length).toBe(3)
    for (const cb of Array.from(checkboxes)) {
      expect(cb.getAttribute('aria-checked')).toBe('true')
    }
    wrapper.unmount()
  })

  it('renders unchecked when intent says false (independent of any other prop)', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: { name: true, age: false, city: true },
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: true,
        hasHiddenColumns: true,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    const checkboxes = document.body.querySelectorAll(
      'button[role="checkbox"]',
    )
    expect(checkboxes.length).toBe(3)
    // The list renders in column-order (name, age, city); age = unchecked.
    expect(checkboxes[0].getAttribute('aria-checked')).toBe('true')
    expect(checkboxes[1].getAttribute('aria-checked')).toBe('false')
    expect(checkboxes[2].getAttribute('aria-checked')).toBe('true')
    wrapper.unmount()
  })

  it('emits toggle(id, false) when an intent-checked checkbox is clicked', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    const checkboxes = Array.from(
      document.body.querySelectorAll('button[role="checkbox"]'),
    ) as HTMLButtonElement[]
    checkboxes[1].click() // age
    await flushPromises()
    const toggleEvents = wrapper.emitted('toggle') ?? []
    expect(toggleEvents.length).toBeGreaterThan(0)
    const last = toggleEvents[toggleEvents.length - 1]
    expect(last).toEqual(['age', false])
    wrapper.unmount()
  })
})

describe('ColumnManagerMenu — pin toggle', () => {
  it('renders <Pin> when unpinned, <PinOff> when pinned (single button per row)', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: { left: ['name'], right: [] },
        hasOverrides: true,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    // Pin buttons carry data-testid for stable selection.
    const pinButtons = document.body.querySelectorAll(
      '[data-testid^="column-pin-toggle-"]',
    )
    expect(pinButtons.length).toBe(3)
    // No DropdownMenuTrigger remains (single-click toggle, no menu).
    expect(
      document.body.querySelectorAll(
        '[data-testid^="column-pin-toggle-"] [data-state="open"]',
      ).length,
    ).toBe(0)
    // Glyph swap: name (pinned) → PinOff; age, city → Pin.
    const namePin = document.body.querySelector(
      '[data-testid="column-pin-toggle-name"]',
    )!
    const agePin = document.body.querySelector(
      '[data-testid="column-pin-toggle-age"]',
    )!
    expect(namePin.querySelector('[data-icon="pin-off"]')).not.toBeNull()
    expect(agePin.querySelector('[data-icon="pin"]')).not.toBeNull()
    expect(namePin.getAttribute('aria-pressed')).toBe('true')
    expect(agePin.getAttribute('aria-pressed')).toBe('false')
    wrapper.unmount()
  })

  it('emits pin(id, "left") on first click and pin(id, false) on second click', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    const agePin = document.body.querySelector(
      '[data-testid="column-pin-toggle-age"]',
    ) as HTMLButtonElement
    agePin.click()
    await flushPromises()
    const pinEvents = wrapper.emitted('pin') ?? []
    expect(pinEvents[0]).toEqual(['age', 'left'])

    // Now flip the pinning prop so the next click toggles off.
    await wrapper.setProps({
      pinning: { left: ['age'], right: [] },
    })
    await flushPromises()
    await nextTick()
    const agePinAfter = document.body.querySelector(
      '[data-testid="column-pin-toggle-age"]',
    ) as HTMLButtonElement
    agePinAfter.click()
    await flushPromises()
    const allEvents = wrapper.emitted('pin') ?? []
    expect(allEvents[allEvents.length - 1]).toEqual(['age', false])
    wrapper.unmount()
  })

  it('does not render a pin button when col.canPin is false', async () => {
    const colsNoPin = [
      { id: 'name', label: 'Name', canResize: true, canPin: true },
      { id: 'age', label: 'Age', canResize: true, canPin: false },
    ]
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns: colsNoPin,
        intent: { name: true, age: true },
        order: ['name', 'age'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    expect(
      document.body.querySelector('[data-testid="column-pin-toggle-name"]'),
    ).not.toBeNull()
    expect(
      document.body.querySelector('[data-testid="column-pin-toggle-age"]'),
    ).toBeNull()
    wrapper.unmount()
  })
})

describe('ColumnManagerMenu — reorder (native HTML5 drag-and-drop)', () => {
  // The label text rendered in each row, in DOM order — the rendered order
  // is the contract drag-and-drop manipulates.
  function renderedLabels(): string[] {
    const rows = document.body.querySelectorAll('[draggable="true"]')
    return Array.from(rows).map((r) =>
      (r.querySelector('span.truncate')?.textContent ?? '').trim(),
    )
  }

  it('renders rows in the order given by the order prop', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['city', 'name', 'age'],
        pinning: emptyPinning(),
        hasOverrides: true,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    expect(renderedLabels()).toEqual(['City', 'Name', 'Age'])

    // Re-ordering the order prop re-renders rows in the new order.
    await wrapper.setProps({ order: ['age', 'city', 'name'] })
    await flushPromises()
    await nextTick()
    expect(renderedLabels()).toEqual(['Age', 'City', 'Name'])
    wrapper.unmount()
  })

  // A DragEvent stand-in: jsdom has no DataTransfer, so attach a stub so the
  // component's ``setData`` / ``effectAllowed`` seeding (the Firefox fix) runs
  // and can be asserted.
  function dragEvent(type: string): Event & { dataTransfer: DataTransferStub } {
    const ev = new Event(type, { bubbles: true })
    const dataTransfer: DataTransferStub = {
      effectAllowed: '',
      dropEffect: '',
      setData: vi.fn(),
      getData: () => '',
    }
    Object.defineProperty(ev, 'dataTransfer', { value: dataTransfer })
    return ev as Event & { dataTransfer: DataTransferStub }
  }

  it('emits reorder + seeds dataTransfer when dragged FROM THE HANDLE onto another row', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    const rows = document.body.querySelectorAll(
      '[draggable="true"]',
    ) as NodeListOf<HTMLElement>
    expect(rows.length).toBe(3)

    // Drag must START on the grip handle (drag-handle), not the row chrome.
    // jsdom doesn't run a real DnD session, so dispatch the native events the
    // component listens for directly: dragstart on the handle, drop on target.
    const handle0 = rows[0].querySelector('.drag-handle') as HTMLElement
    const startEv = dragEvent('dragstart')
    handle0.dispatchEvent(startEv)
    rows[2].dispatchEvent(dragEvent('drop'))
    await flushPromises()
    await nextTick()

    // The Firefox fix: a move effect + payload were seeded on dragstart.
    expect(startEv.dataTransfer.effectAllowed).toBe('move')
    expect(startEv.dataTransfer.setData).toHaveBeenCalledWith('text/plain', '0')

    const reorderEvents = wrapper.emitted('reorder') ?? []
    expect(reorderEvents.length).toBe(1)
    // name moves from index 0 to index 2 → [age, city, name].
    expect(reorderEvents[0]).toEqual([['age', 'city', 'name']])
    wrapper.unmount()
  })

  it('does NOT reorder when a drag starts off the handle (e.g. on the row body)', async () => {
    const wrapper = mount(ColumnManagerMenu, {
      props: {
        columns,
        intent: emptyIntent(),
        order: ['name', 'age', 'city'],
        pinning: emptyPinning(),
        hasOverrides: false,
        hasHiddenColumns: false,
        defaultOpen: true,
      },
      attachTo: document.body,
    })
    await flushPromises()
    await nextTick()
    const rows = document.body.querySelectorAll(
      '[draggable="true"]',
    ) as NodeListOf<HTMLElement>

    // Dragstart whose target is the row itself (not the handle) is cancelled,
    // so a subsequent drop is a no-op — no reorder is emitted.
    rows[0].dispatchEvent(dragEvent('dragstart'))
    rows[2].dispatchEvent(dragEvent('drop'))
    await flushPromises()
    await nextTick()

    expect(wrapper.emitted('reorder')).toBeUndefined()
    wrapper.unmount()
  })
})

interface DataTransferStub {
  effectAllowed: string
  dropEffect: string
  setData: ReturnType<typeof vi.fn>
  getData: () => string
}

// Quiet the unused-import lint by referencing h.
void h

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Columns3,
  GripVertical,
  Pin,
  PinOff,
  RotateCcw,
} from 'lucide-vue-next'
import { Popover, PopoverContent, PopoverTrigger } from './popover'
import { Button } from '@/shared/ui/button'
import { Checkbox } from './checkbox'
import type { ColumnPinningState } from '@tanstack/vue-table'
import type { PinSide } from './useDataTable'

export interface ColumnManagerColumn {
  id: string
  label: string
  canResize?: boolean
  canPin?: boolean
}

const props = defineProps<{
  columns: ColumnManagerColumn[]
  /**
   * Form-binding state — what the checkbox reflects. Defaults to ✓ for
   * every togglable column unless the user has explicitly hidden it.
   * Sourced from ``useColumnVisibility``'s ``userVisibilityIntent``.
   * The runtime layout adjustment from ``responsiveHidden`` is
   * deliberately invisible here so the form always shows user intent.
   */
  intent: Record<string, boolean>
  /** Effective order state fed by `useColumnManager`. */
  order: string[]
  /** Effective pinning state fed by `useColumnManager`. */
  pinning: ColumnPinningState
  /** ``true`` iff any user customisation exists (visibility/order/pinning/sizing). Drives the popover's "Reset" button. */
  hasOverrides?: boolean
  /**
   * ``true`` iff the user has explicitly hidden at least one column.
   * Drives the trigger-button "filtering active" dot. Reorder and pin
   * are user customisations, not "filtering" — they do not light this.
   */
  hasHiddenColumns?: boolean
  /**
   * Pass-through to ``<Popover>``'s ``default-open``. Used by component
   * tests to render the popover content on mount; production callers
   * should leave it false.
   */
  defaultOpen?: boolean
  /**
   * When true, the trigger renders icon-only with no "Columns" label.
   * Used by dense list surfaces (e.g. /connections) where the filter
   * bar already carries enough chrome.
   */
  iconOnly?: boolean
}>()

const emit = defineEmits<{
  toggle: [id: string, visible: boolean]
  reorder: [ids: string[]]
  pin: [id: string, side: PinSide]
  reset: []
}>()

/**
 * Items in current effective order. Native HTML5 drag-and-drop reorders
 * this list via ``onDrop``; the setter emits ``reorder`` with the new id
 * sequence.
 */
const items = computed<ColumnManagerColumn[]>({
  get() {
    const byId = new Map(props.columns.map((c) => [c.id, c]))
    const seen = new Set<string>()
    const out: ColumnManagerColumn[] = []
    for (const id of props.order) {
      const col = byId.get(id)
      if (col) {
        out.push(col)
        seen.add(id)
      }
    }
    for (const col of props.columns) {
      if (!seen.has(col.id)) out.push(col)
    }
    return out
  },
  set(next) {
    emit(
      'reorder',
      next.map((c) => c.id),
    )
  },
})

// Index of the row currently being dragged (native HTML5 DnD). ``null``
// when no drag is in progress; drives the ghost/opacity style.
const dragIndex = ref<number | null>(null)

// Start a reorder drag ONLY from the grip handle — so dragging on the
// checkbox, label, or pin button never initiates a row move. Seeding
// ``dataTransfer`` (with a move effect) is required for native DnD to start at
// all in Firefox; without it the drag silently never begins.
function onDragStart(i: number, e: DragEvent): void {
  const target = e.target as HTMLElement | null
  if (!target?.closest('.drag-handle')) {
    e.preventDefault()
    return
  }
  dragIndex.value = i
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(i))
  }
}

function onDragOver(e: DragEvent): void {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

function onDrop(target: number): void {
  const from = dragIndex.value
  dragIndex.value = null
  if (from === null || from === target) return
  const next = [...items.value]
  const [moved] = next.splice(from, 1)
  if (!moved) return
  next.splice(target, 0, moved)
  // Assigning back through the computed setter emits ``reorder`` with the
  // reordered id list — identical contract to the previous VueDraggable wiring.
  items.value = next
}

function isPinnedLeft(id: string): boolean {
  return !!props.pinning.left?.includes(id)
}

function onPinClick(id: string) {
  emit('pin', id, isPinnedLeft(id) ? false : 'left')
}

const triggerLabel = computed(() =>
  props.hasHiddenColumns
    ? 'Manage columns, filtering active'
    : 'Manage columns',
)
</script>

<template>
  <Popover :default-open="defaultOpen">
    <PopoverTrigger as-child>
      <Button
        :variant="iconOnly ? 'ghost' : 'outline'"
        :size="iconOnly ? 'icon' : 'sm'"
        :class="
          iconOnly
            ? 'relative h-9 w-9'
            : 'relative h-9 gap-1.5 border-dashed text-xs'
        "
        :aria-label="triggerLabel"
      >
        <Columns3 class="h-3.5 w-3.5" />
        <span v-if="!iconOnly">Columns</span>
        <span
          v-if="hasHiddenColumns"
          data-testid="column-manager-filter-indicator"
          aria-hidden="true"
          class="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-primary"
        />
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-72" align="end">
      <div class="flex items-center justify-between pb-2">
        <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Columns
        </div>
        <Button
          v-if="hasOverrides"
          variant="ghost"
          size="sm"
          class="h-6 px-1.5 text-xs"
          @click="emit('reset')"
        >
          <RotateCcw class="mr-1 h-3 w-3" /> Reset
        </Button>
      </div>
      <div class="-mx-1 flex flex-col gap-0.5">
        <div
          v-for="(col, i) in items"
          :key="col.id"
          class="group flex items-center gap-1.5 rounded-sm px-1 py-1 hover:bg-muted/60"
          :class="{ 'dt-manager-dragging': dragIndex === i }"
          draggable="true"
          @dragstart="onDragStart(i, $event)"
          @dragover="onDragOver"
          @drop.prevent="onDrop(i)"
          @dragend="dragIndex = null"
        >
          <button
            type="button"
            class="drag-handle flex h-6 w-5 shrink-0 cursor-grab items-center justify-center text-muted-foreground active:cursor-grabbing"
            :aria-label="`Drag ${col.label} to reorder`"
          >
            <GripVertical class="h-3.5 w-3.5" />
          </button>
          <label class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              :checked="intent[col.id] !== false"
              :aria-label="`Show ${col.label}`"
              @update:checked="(v) => emit('toggle', col.id, !!v)"
            />
            <span class="truncate">{{ col.label }}</span>
          </label>
          <Button
            v-if="col.canPin !== false"
            variant="ghost"
            size="icon"
            class="h-6 w-6 text-muted-foreground"
            :data-testid="`column-pin-toggle-${col.id}`"
            :aria-pressed="isPinnedLeft(col.id)"
            :aria-label="
              isPinnedLeft(col.id)
                ? `Unpin ${col.label}`
                : `Pin ${col.label} to left`
            "
            @click="onPinClick(col.id)"
          >
            <PinOff
              v-if="isPinnedLeft(col.id)"
              data-icon="pin-off"
              class="h-3.5 w-3.5 text-primary"
            />
            <Pin v-else data-icon="pin" class="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </PopoverContent>
  </Popover>
</template>

<style scoped>
.dt-manager-dragging {
  opacity: 0.4;
}
</style>

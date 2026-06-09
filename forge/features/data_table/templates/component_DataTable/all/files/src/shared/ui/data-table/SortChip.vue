<script setup lang="ts" generic="T">
/**
 * Sort selector for the list-tier layout. Headers aren't visible in card
 * mode, so users need a separate affordance to change ordering. The chip
 * shows the current sort column + direction; the dropdown lists every
 * sortable column with an active marker.
 */
import { computed } from 'vue'
import {
  ArrowDown,
  ArrowDownUp,
  ArrowUp,
  Check,
} from 'lucide-vue-next'
import type { Table } from '@tanstack/vue-table'
import { Button } from '@/shared/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/ui/dropdown-menu'

const props = defineProps<{
  table: Table<T>
}>()

const sortableColumns = computed(() =>
  props.table
    .getAllColumns()
    .filter((c) => c.getCanSort())
    .map((c) => ({
      id: c.id,
      label:
        typeof c.columnDef.header === 'string'
          ? c.columnDef.header
          : (c.id ?? ''),
      column: c,
    })),
)

const activeSort = computed(() => {
  const sorted = sortableColumns.value.find((c) => c.column.getIsSorted())
  return sorted ?? null
})

const directionLabel = computed(() => {
  const c = activeSort.value?.column
  if (!c) return null
  return c.getIsSorted() === 'desc' ? 'desc' : 'asc'
})

function pick(colId: string) {
  const col = props.table.getColumn(colId)
  if (!col) return
  // Cycle: not-sorted → asc → desc → not-sorted, but bias to asc on first pick.
  const current = col.getIsSorted()
  if (current === false) col.toggleSorting(false) // asc
  else if (current === 'asc') col.toggleSorting(true) // desc
  else col.clearSorting()
}

function clearSort() {
  props.table.resetSorting()
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button
        variant="outline"
        size="sm"
        class="h-9 gap-1.5 border-dashed text-xs"
        aria-label="Sort records"
      >
        <ArrowDownUp class="h-3.5 w-3.5" />
        <span v-if="activeSort">
          {{ activeSort.label }}
          <ArrowUp v-if="directionLabel === 'asc'" class="ml-0.5 inline h-3 w-3" />
          <ArrowDown v-else class="ml-0.5 inline h-3 w-3" />
        </span>
        <span v-else class="text-muted-foreground">Sort</span>
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" class="w-56">
      <DropdownMenuLabel class="text-xs">Sort by</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        v-for="col in sortableColumns"
        :key="col.id"
        class="flex items-center justify-between gap-2"
        @select="pick(col.id)"
      >
        <span class="truncate">{{ col.label }}</span>
        <span class="flex items-center gap-1 text-xs text-muted-foreground">
          <ArrowUp
            v-if="col.column.getIsSorted() === 'asc'"
            class="h-3 w-3"
          />
          <ArrowDown
            v-else-if="col.column.getIsSorted() === 'desc'"
            class="h-3 w-3"
          />
          <Check
            v-if="col.column.getIsSorted()"
            class="h-3 w-3 text-primary"
          />
        </span>
      </DropdownMenuItem>
      <DropdownMenuSeparator v-if="activeSort" />
      <DropdownMenuItem
        v-if="activeSort"
        class="text-muted-foreground"
        @select="clearSort"
      >
        Clear sort
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>

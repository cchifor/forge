<script setup lang="ts">
import { ref, computed } from 'vue'
import { ArrowUp, ArrowDown, Search } from 'lucide-vue-next'
import { Input } from '@/shared/ui/input'
import { Button } from '@/shared/ui/button'
import type { WorkspaceActivity, AgentState } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const schema = computed(() => props.activity.content.props || props.activity.content)
const columns = computed(() => schema.value.columns || [])
const allRows = computed(() => schema.value.rows || [])
const pageSize = computed(() => schema.value.pageSize || 25)

const sortKey = ref(schema.value.defaultSort?.key || '')
const sortDir = ref<'asc' | 'desc'>(schema.value.defaultSort?.direction || 'asc')
const filterText = ref('')
const currentPage = ref(1)
const selectedIds = ref<Set<number | string>>(new Set())

const filterableColumns = computed(() => columns.value.filter((c: any) => c.filterable))

const filteredRows = computed(() => {
  if (!filterText.value) return allRows.value
  const q = filterText.value.toLowerCase()
  return allRows.value.filter((row: any) =>
    columns.value.some((col: any) => {
      const val = row[col.key]
      return val !== null && val !== undefined && String(val).toLowerCase().includes(q)
    }),
  )
})

const sortedRows = computed(() => {
  if (!sortKey.value) return filteredRows.value
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...filteredRows.value].sort((a: any, b: any) => {
    const av = a[key] ?? ''
    const bv = b[key] ?? ''
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av).localeCompare(String(bv)) * dir
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(sortedRows.value.length / pageSize.value)))
const pagedRows = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return sortedRows.value.slice(start, start + pageSize.value)
})

function toggleSort(key: string) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
  currentPage.value = 1
}

function toggleSelect(id: number | string) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedIds.value = s
}

function formatCell(value: any, col: any): string {
  if (value === null || value === undefined || value === '') return '—'
  if (col.format === 'duration') {
    if (value === 0) return '—'
    return value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(1)}s`
  }
  if (col.type === 'date') {
    if (!value) return '—'
    try { return new Date(value).toLocaleString() } catch { return String(value) }
  }
  if (col.truncate && String(value).length > col.truncate) {
    return String(value).slice(0, col.truncate) + '...'
  }
  return String(value)
}

const badgeColors: Record<string, string> = {
  completed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  running: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  pending: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  failed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  skipped: 'bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500',
}
</script>

<template>
  <div class="flex h-full flex-col p-4">
    <div class="mb-4 flex items-center justify-between">
      <h2 class="text-lg font-semibold">{{ schema.title }}</h2>
      <div class="relative w-64">
        <Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input v-model="filterText" placeholder="Filter..." class="pl-8 h-9 text-sm" />
      </div>
    </div>

    <div class="flex-1 overflow-auto rounded-lg border">
      <table class="w-full text-sm">
        <thead class="sticky top-0 z-10 bg-muted/80 backdrop-blur">
          <tr>
            <th v-if="schema.selectable" class="w-10 px-3 py-2" />
            <th
              v-for="col in columns"
              :key="col.key"
              class="px-3 py-2 text-left font-medium text-muted-foreground"
              :class="col.sortable ? 'cursor-pointer select-none hover:text-foreground' : ''"
              @click="col.sortable && toggleSort(col.key)"
            >
              <div class="flex items-center gap-1">
                {{ col.label }}
                <template v-if="col.sortable && sortKey === col.key">
                  <ArrowUp v-if="sortDir === 'asc'" class="h-3 w-3" />
                  <ArrowDown v-else class="h-3 w-3" />
                </template>
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in pagedRows"
            :key="row.id"
            class="border-t transition-colors hover:bg-muted/50"
            :class="selectedIds.has(row.id) ? 'bg-primary/5' : ''"
          >
            <td v-if="schema.selectable" class="px-3 py-2">
              <input
                type="checkbox"
                :checked="selectedIds.has(row.id)"
                class="h-4 w-4 rounded border-input"
                @change="toggleSelect(row.id)"
              />
            </td>
            <td v-for="col in columns" :key="col.key" class="px-3 py-2">
              <span
                v-if="col.type === 'badge'"
                class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium"
                :class="badgeColors[row[col.key]] || badgeColors.pending"
              >
                {{ row[col.key] }}
              </span>
              <span v-else>{{ formatCell(row[col.key], col) }}</span>
            </td>
          </tr>
          <tr v-if="pagedRows.length === 0">
            <td :colspan="columns.length + (schema.selectable ? 1 : 0)" class="px-3 py-8 text-center text-muted-foreground">
              No matching rows
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-3 flex items-center justify-between text-xs text-muted-foreground">
      <span>{{ filteredRows.length }} rows{{ selectedIds.size ? ` · ${selectedIds.size} selected` : '' }}</span>
      <div class="flex items-center gap-2">
        <Button variant="outline" size="sm" :disabled="currentPage <= 1" class="h-7 text-xs" @click="currentPage--">Prev</Button>
        <span>{{ currentPage }} / {{ totalPages }}</span>
        <Button variant="outline" size="sm" :disabled="currentPage >= totalPages" class="h-7 text-xs" @click="currentPage++">Next</Button>
      </div>
    </div>
  </div>
</template>

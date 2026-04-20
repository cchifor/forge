<!--
  DataTable — tabular data with sortable columns + client-side pagination.

  Props schema: forge/templates/_shared/canvas-components/DataTable.props.schema.json
-->
<script setup lang="ts">
import { computed, ref } from 'vue'

interface Column {
  key: string
  label: string
  sortable?: boolean
}

interface Props {
  columns: Column[]
  rows: Record<string, unknown>[]
  pageSize?: number
}

const props = defineProps<Props>()

const sortKey = ref<string | null>(null)
const sortDir = ref<'asc' | 'desc'>('asc')
const page = ref(0)

function toggleSort(column: Column) {
  if (!column.sortable) return
  if (sortKey.value === column.key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = column.key
    sortDir.value = 'asc'
  }
}

const sortedRows = computed(() => {
  const rows = [...props.rows]
  if (sortKey.value) {
    const key = sortKey.value
    rows.sort((a, b) => {
      const av = a[key]
      const bv = b[key]
      if (av == null) return 1
      if (bv == null) return -1
      if (av < bv) return sortDir.value === 'asc' ? -1 : 1
      if (av > bv) return sortDir.value === 'asc' ? 1 : -1
      return 0
    })
  }
  return rows
})

const pageSize = computed(() => props.pageSize ?? 25)
const totalPages = computed(() =>
  Math.max(1, Math.ceil(sortedRows.value.length / pageSize.value)),
)
const pagedRows = computed(() =>
  sortedRows.value.slice(page.value * pageSize.value, (page.value + 1) * pageSize.value),
)

function goTo(p: number) {
  page.value = Math.max(0, Math.min(totalPages.value - 1, p))
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <div class="forge-canvas-table">
    <table>
      <thead>
        <tr>
          <th
            v-for="col in props.columns"
            :key="col.key"
            :class="{ 'is-sortable': col.sortable }"
            @click="toggleSort(col)"
          >
            {{ col.label }}
            <span
              v-if="col.sortable"
              class="forge-canvas-table__sort"
              :data-dir="sortKey === col.key ? sortDir : ''"
            >
              {{ sortKey === col.key ? (sortDir === 'asc' ? '▲' : '▼') : '↕' }}
            </span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in pagedRows" :key="i">
          <td v-for="col in props.columns" :key="col.key">
            {{ formatCell(row[col.key]) }}
          </td>
        </tr>
        <tr v-if="pagedRows.length === 0">
          <td :colspan="props.columns.length" class="forge-canvas-table__empty">
            No rows.
          </td>
        </tr>
      </tbody>
    </table>
    <footer v-if="totalPages > 1" class="forge-canvas-table__footer">
      <button type="button" :disabled="page === 0" @click="goTo(page - 1)">← Prev</button>
      <span>Page {{ page + 1 }} / {{ totalPages }}</span>
      <button type="button" :disabled="page >= totalPages - 1" @click="goTo(page + 1)">Next →</button>
    </footer>
  </div>
</template>

<style scoped>
.forge-canvas-table { background: var(--fc-surface, #fff); border: 1px solid var(--fc-border, #e5e7eb); border-radius: 0.5rem; overflow: hidden; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
th, td { padding: 0.625rem 0.75rem; text-align: left; border-bottom: 1px solid var(--fc-border, #e5e7eb); }
th { background: var(--fc-muted, #f9fafb); font-weight: 600; user-select: none; }
th.is-sortable { cursor: pointer; }
th.is-sortable:hover { background: var(--fc-muted-fg, #f3f4f6); }
.forge-canvas-table__sort { margin-left: 0.25rem; font-size: 0.75rem; color: var(--fc-muted-fg, #9ca3af); }
.forge-canvas-table__sort[data-dir] { color: var(--fc-primary, #2563eb); }
.forge-canvas-table__empty { text-align: center; color: var(--fc-muted-fg, #6b7280); padding: 2rem; }
.forge-canvas-table__footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.5rem 0.75rem; background: var(--fc-muted, #f9fafb); border-top: 1px solid var(--fc-border, #e5e7eb); font-size: 0.8rem; }
.forge-canvas-table__footer button { padding: 0.25rem 0.625rem; border: 1px solid var(--fc-border, #e5e7eb); background: var(--fc-surface, #fff); border-radius: 0.25rem; cursor: pointer; }
.forge-canvas-table__footer button:disabled { opacity: 0.4; cursor: not-allowed; }
</style>

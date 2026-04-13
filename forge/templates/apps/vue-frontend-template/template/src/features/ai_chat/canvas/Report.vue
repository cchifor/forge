<script setup lang="ts">
import { computed } from 'vue'
import { TrendingUp, TrendingDown, Minus } from 'lucide-vue-next'
import { marked } from 'marked'
import type { WorkspaceActivity, AgentState } from '../types'

marked.setOptions({ breaks: true, gfm: true })

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const schema = computed(() => props.activity.content.props || props.activity.content)
const sections = computed(() => schema.value.sections || [])

function renderMarkdown(content: string): string {
  return marked.parse(content) as string
}

// Simple bar chart using CSS
function barMax(dataset: any): number {
  return Math.max(...(dataset.data || []), 1)
}

const trendColors: Record<string, string> = {
  up: 'text-emerald-600 dark:text-emerald-400',
  down: 'text-red-600 dark:text-red-400',
  neutral: 'text-muted-foreground',
}
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-6 p-6">
    <!-- Header -->
    <div>
      <h2 class="text-xl font-bold">{{ schema.title }}</h2>
      <p v-if="schema.generated_at" class="text-xs text-muted-foreground">
        Generated {{ new Date(schema.generated_at).toLocaleString() }}
      </p>
    </div>

    <!-- Sections -->
    <template v-for="(section, idx) in sections" :key="idx">
      <!-- Metrics -->
      <div v-if="section.type === 'metrics'">
        <h3 v-if="section.title" class="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">{{ section.title }}</h3>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div
            v-for="item in section.items"
            :key="item.label"
            class="rounded-lg border p-3"
          >
            <p class="text-xs text-muted-foreground">{{ item.label }}</p>
            <p class="mt-1 text-2xl font-bold">{{ item.value }}</p>
            <div v-if="item.change" class="mt-1 flex items-center gap-1 text-xs" :class="trendColors[item.trend] || trendColors.neutral">
              <TrendingUp v-if="item.trend === 'up'" class="h-3 w-3" />
              <TrendingDown v-else-if="item.trend === 'down'" class="h-3 w-3" />
              <Minus v-else class="h-3 w-3" />
              {{ item.change }}
            </div>
          </div>
        </div>
      </div>

      <!-- Chart (CSS bar chart) -->
      <div v-else-if="section.type === 'chart'">
        <h3 v-if="section.title" class="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">{{ section.title }}</h3>
        <div class="rounded-lg border p-4">
          <div
            v-for="dataset in (section.data?.datasets || [])"
            :key="dataset.label"
            class="space-y-1"
          >
            <div
              v-for="(val, i) in dataset.data"
              :key="i"
              class="flex items-center gap-2"
            >
              <span class="w-8 text-right text-xs text-muted-foreground">{{ section.data.labels?.[i] || i }}</span>
              <div class="flex-1 h-6 rounded bg-muted overflow-hidden">
                <div
                  class="h-full rounded bg-primary transition-all"
                  :style="{ width: `${(val / barMax(dataset)) * 100}%` }"
                />
              </div>
              <span class="w-16 text-right text-xs tabular-nums">{{ val.toLocaleString() }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Table -->
      <div v-else-if="section.type === 'table'">
        <h3 v-if="section.title" class="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">{{ section.title }}</h3>
        <div class="overflow-auto rounded-lg border">
          <table class="w-full text-sm">
            <thead class="bg-muted/50">
              <tr>
                <th v-for="col in section.columns" :key="col.key" class="px-3 py-2 text-left font-medium text-muted-foreground">
                  {{ col.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in section.rows" :key="ri" class="border-t">
                <td v-for="col in section.columns" :key="col.key" class="px-3 py-2">
                  {{ row[col.key] }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Markdown -->
      <div v-else-if="section.type === 'markdown'" class="prose prose-sm dark:prose-invert max-w-none">
        <div v-html="renderMarkdown(section.content || '')" />
      </div>
    </template>
  </div>
</template>

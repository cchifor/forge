<script setup lang="ts">
import { computed } from 'vue'
import { Check, Loader2, Clock, XCircle, SkipForward } from 'lucide-vue-next'
import type { WorkspaceActivity, AgentState } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const schema = computed(() => props.activity.content.props || props.activity.content)
const nodes = computed(() => schema.value.nodes || [])
const isHorizontal = computed(() => schema.value.layout !== 'vertical')

const statusConfig: Record<string, { bg: string; border: string; text: string; icon: any }> = {
  completed: { bg: 'bg-emerald-50 dark:bg-emerald-950/30', border: 'border-emerald-300 dark:border-emerald-700', text: 'text-emerald-700 dark:text-emerald-400', icon: Check },
  running: { bg: 'bg-blue-50 dark:bg-blue-950/30', border: 'border-blue-300 dark:border-blue-700', text: 'text-blue-700 dark:text-blue-400', icon: Loader2 },
  pending: { bg: 'bg-gray-50 dark:bg-gray-900', border: 'border-gray-200 dark:border-gray-700', text: 'text-gray-500 dark:text-gray-400', icon: Clock },
  failed: { bg: 'bg-red-50 dark:bg-red-950/30', border: 'border-red-300 dark:border-red-700', text: 'text-red-700 dark:text-red-400', icon: XCircle },
  skipped: { bg: 'bg-gray-50 dark:bg-gray-900', border: 'border-gray-200 dark:border-gray-800', text: 'text-gray-400 dark:text-gray-500', icon: SkipForward },
}

function getConfig(status: string) {
  return statusConfig[status] || statusConfig.pending
}

function handleRetry(nodeId: string) {
  emit('action', { type: 'workflow_action', data: { action: 'retry', nodeId } })
}
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center p-8">
    <h2 class="mb-8 text-lg font-semibold">{{ schema.title }}</h2>

    <div
      class="flex items-center gap-2"
      :class="isHorizontal ? 'flex-row' : 'flex-col'"
    >
      <template v-for="(node, idx) in nodes" :key="node.id">
        <!-- Connector arrow -->
        <div
          v-if="idx > 0"
          class="flex items-center justify-center text-muted-foreground/40"
          :class="isHorizontal ? 'w-8' : 'h-8'"
        >
          <svg v-if="isHorizontal" viewBox="0 0 32 16" class="h-4 w-8">
            <line x1="0" y1="8" x2="24" y2="8" stroke="currentColor" stroke-width="2" />
            <polygon points="24,4 32,8 24,12" fill="currentColor" />
          </svg>
          <svg v-else viewBox="0 0 16 32" class="h-8 w-4">
            <line x1="8" y1="0" x2="8" y2="24" stroke="currentColor" stroke-width="2" />
            <polygon points="4,24 8,32 12,24" fill="currentColor" />
          </svg>
        </div>

        <!-- Node -->
        <div
          class="flex flex-col items-center gap-2 rounded-xl border-2 px-6 py-4 transition-shadow min-w-[140px]"
          :class="[getConfig(node.status).bg, getConfig(node.status).border, node.status === 'running' ? 'shadow-md' : '']"
        >
          <div class="flex items-center gap-2" :class="getConfig(node.status).text">
            <component
              :is="getConfig(node.status).icon"
              class="h-5 w-5"
              :class="node.status === 'running' ? 'animate-spin' : ''"
            />
            <span class="font-semibold text-sm">{{ node.label }}</span>
          </div>

          <p v-if="node.detail" class="text-xs text-muted-foreground text-center">{{ node.detail }}</p>

          <!-- Progress bar -->
          <div v-if="node.progress !== undefined && node.status === 'running'" class="w-full h-1.5 rounded-full bg-muted overflow-hidden">
            <div class="h-full rounded-full bg-blue-500 transition-all" :style="{ width: `${node.progress}%` }" />
          </div>

          <!-- Retry button for failed nodes -->
          <button
            v-if="node.status === 'failed'"
            class="mt-1 text-xs text-red-600 hover:underline"
            @click="handleRetry(node.id)"
          >
            Retry
          </button>
        </div>
      </template>
    </div>
  </div>
</template>

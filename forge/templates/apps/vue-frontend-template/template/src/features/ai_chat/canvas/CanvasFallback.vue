<script setup lang="ts">
import { Sparkles } from 'lucide-vue-next'
import type { WorkspaceActivity, AgentState } from '../types'

defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
    <div class="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
      <Sparkles class="h-8 w-8 text-muted-foreground" />
    </div>
    <div class="space-y-1">
      <p class="text-sm font-medium text-foreground">{{ activity.activityType }}</p>
      <p class="max-w-sm text-xs text-muted-foreground">
        No renderer registered for this activity type.
      </p>
    </div>
    <pre
      v-if="activity.content"
      class="max-h-64 max-w-lg overflow-auto rounded-lg border bg-muted/50 p-3 text-left text-xs"
    >{{ JSON.stringify(activity.content, null, 2) }}</pre>
  </div>
</template>

<script setup lang="ts">
import type { WorkspaceActivity, AgentState } from '../types'

defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()
</script>

<template>
  <div class="flex flex-col gap-4 p-4">
    <h3 class="text-sm font-medium text-muted-foreground">
      {{ activity.activityType }}
    </h3>
    <pre
      class="overflow-auto rounded-lg border bg-muted/50 p-4 text-xs leading-relaxed text-foreground"
    >{{ JSON.stringify(activity.content, null, 2) }}</pre>
  </div>
</template>

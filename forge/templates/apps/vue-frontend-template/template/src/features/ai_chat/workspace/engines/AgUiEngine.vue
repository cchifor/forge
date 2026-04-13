<script setup lang="ts">
import { computed } from 'vue'
import { resolveWorkspaceComponent } from '../registry'
import type { WorkspaceActivity, AgentState } from '../../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const resolved = computed(() => resolveWorkspaceComponent(props.activity.activityType))
</script>

<template>
  <component
    :is="resolved.component"
    :activity="activity"
    :state="state"
    @action="$emit('action', $event)"
  />
</template>

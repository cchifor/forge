<script setup lang="ts">
import { computed } from 'vue'
import { Check, X } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import type { WorkspaceActivity, AgentState, WorkspaceAction } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: WorkspaceAction]
}>()

const toolName = computed(() => props.activity.content.toolName || 'Unknown Tool')
const toolCallId = computed(() => props.activity.content.toolCallId || '')
const args = computed(() => props.activity.content.arguments || props.activity.content.args || {})
const diff = computed(() => props.activity.content.diff || null)

const formattedArgs = computed(() => {
  try {
    return JSON.stringify(args.value, null, 2)
  } catch {
    return String(args.value)
  }
})

function approve() {
  emit('action', {
    type: 'tool_approval',
    data: { toolCallId: toolCallId.value, approved: true },
  })
}

function reject() {
  emit('action', {
    type: 'tool_approval',
    data: { toolCallId: toolCallId.value, approved: false },
  })
}
</script>

<template>
  <div class="flex flex-col gap-4 p-4">
    <div class="flex flex-col gap-1">
      <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">Tool Call</span>
      <span class="text-sm font-semibold">{{ toolName }}</span>
    </div>

    <div class="flex flex-col gap-1">
      <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">Arguments</span>
      <pre
        class="overflow-auto rounded-lg border bg-muted/50 p-3 text-xs leading-relaxed text-foreground"
      >{{ formattedArgs }}</pre>
    </div>

    <div v-if="diff" class="flex flex-col gap-1">
      <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">Diff Preview</span>
      <pre
        class="overflow-auto rounded-lg border bg-muted/50 p-3 text-xs leading-relaxed text-foreground"
      >{{ diff }}</pre>
    </div>

    <div class="flex gap-3 pt-2">
      <Button
        class="flex-1 bg-emerald-600 text-white hover:bg-emerald-700"
        @click="approve"
      >
        <Check class="mr-1.5 h-4 w-4" />
        Approve
      </Button>
      <Button
        variant="outline"
        class="flex-1 border-destructive text-destructive hover:bg-destructive hover:text-destructive-foreground"
        @click="reject"
      >
        <X class="mr-1.5 h-4 w-4" />
        Reject
      </Button>
    </div>
  </div>
</template>

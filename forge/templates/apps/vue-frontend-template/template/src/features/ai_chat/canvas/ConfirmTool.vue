<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import type { WorkspaceActivity, AgentState } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: { type: string; toolCallId?: string; data: Record<string, any> }]
}>()

const toolCallId = computed(() => props.activity.content._toolCallId as string | undefined)
const schema = computed(() => props.activity.content.props || props.activity.content)

function decide(approved: boolean) {
  emit('action', { type: 'approval_decision', toolCallId: toolCallId.value, data: { approved } })
}
</script>

<template>
  <div class="mx-auto flex max-w-xl flex-col gap-6 p-6">
    <div class="flex items-start gap-3">
      <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted">
        <CheckCircle class="h-5 w-5 text-muted-foreground" />
      </div>
      <div class="space-y-1">
        <h2 class="text-lg font-semibold">{{ schema.title }}</h2>
        <p class="text-sm text-foreground">{{ schema.message }}</p>
      </div>
    </div>

    <pre
      v-if="schema.details"
      class="max-h-64 overflow-auto rounded-lg border bg-muted/50 p-3 text-left text-xs whitespace-pre-wrap"
    >{{ schema.details }}</pre>

    <div class="flex gap-3 pt-2">
      <Button @click="decide(true)">{{ schema.confirmLabel || 'Approve' }}</Button>
      <Button variant="outline" @click="decide(false)">{{ schema.cancelLabel || 'Reject' }}</Button>
    </div>
  </div>
</template>

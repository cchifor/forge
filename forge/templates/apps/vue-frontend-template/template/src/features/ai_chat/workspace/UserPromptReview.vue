<script setup lang="ts">
import { ref, computed } from 'vue'
import { Star, ArrowUp } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import type { WorkspaceActivity, AgentState, WorkspaceAction } from '../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: WorkspaceAction]
}>()

const question = computed(() => props.activity.content.question || '')
const options = computed(() => props.activity.content.options || [])
const toolCallId = computed(() => props.activity.content.tool_call_id || props.activity.content.toolCallId || '')

const customAnswer = ref('')

function respond(answer: string) {
  emit('action', {
    type: 'hitl_response',
    data: { toolCallId: toolCallId.value, answer },
  })
}

function submitCustom() {
  const text = customAnswer.value.trim()
  if (text) {
    respond(text)
    customAnswer.value = ''
  }
}
</script>

<template>
  <div class="flex flex-col gap-4 p-4">
    <div class="flex flex-col gap-1">
      <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">Question</span>
      <p class="text-sm font-medium text-foreground">{{ question }}</p>
    </div>

    <div v-if="options.length > 0" class="flex flex-col gap-2">
      <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">Options</span>
      <button
        v-for="opt in options"
        :key="opt.label"
        class="group flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors hover:border-primary hover:bg-primary/5"
        :class="opt.recommended === 'true'
          ? 'border-primary/40 bg-primary/5'
          : 'border-border bg-background'"
        @click="respond(opt.label)"
      >
        <Star
          v-if="opt.recommended === 'true'"
          class="mt-0.5 h-4 w-4 shrink-0 fill-primary text-primary"
        />
        <div class="flex flex-col gap-0.5">
          <span class="text-sm font-medium text-foreground">{{ opt.label }}</span>
          <span v-if="opt.description" class="text-xs leading-relaxed text-muted-foreground">
            {{ opt.description }}
          </span>
        </div>
      </button>
    </div>

    <div class="flex flex-col gap-1 pt-2">
      <span class="text-xs font-medium uppercase tracking-wide text-muted-foreground">Custom Answer</span>
      <div class="flex gap-2">
        <Input
          v-model="customAnswer"
          placeholder="Type a custom answer..."
          @keydown.enter.prevent="submitCustom"
        />
        <Button
          variant="ghost"
          size="icon"
          class="h-9 w-9 shrink-0 rounded-full border border-border interactive-press"
          :disabled="!customAnswer.trim()"
          @click="submitCustom"
        >
          <ArrowUp class="h-4 w-4 text-ai-from" />
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { HelpCircle, Star, ArrowUp } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import type { UserPromptPayload } from '../types'

defineProps<{
  prompt: UserPromptPayload
  disabled?: boolean
}>()

const emit = defineEmits<{
  respond: [answer: string]
}>()

const customAnswer = ref('')

function submitCustom() {
  const text = customAnswer.value.trim()
  if (text) {
    emit('respond', text)
    customAnswer.value = ''
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submitCustom()
  }
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- Header -->
    <div class="flex items-center gap-2">
      <div
        class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400"
      >
        <HelpCircle class="h-3.5 w-3.5" />
      </div>
      <span class="text-xs font-medium text-amber-600 dark:text-amber-400">Needs your input</span>
    </div>

    <!-- Question -->
    <div class="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
      <p class="text-sm font-medium text-foreground">{{ prompt.question }}</p>

      <!-- Options -->
      <div v-if="prompt.options.length > 0" class="mt-3 flex flex-col gap-2">
        <button
          v-for="opt in prompt.options"
          :key="opt.label"
          :disabled="disabled"
          class="group flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors hover:border-primary hover:bg-primary/5 disabled:pointer-events-none disabled:opacity-50"
          :class="opt.recommended === 'true'
            ? 'border-primary/40 bg-primary/5'
            : 'border-border bg-background'"
          @click="emit('respond', opt.label)"
        >
          <Star
            v-if="opt.recommended === 'true'"
            class="mt-0.5 h-3.5 w-3.5 shrink-0 fill-primary text-primary"
          />
          <div class="flex flex-col gap-0.5">
            <span class="text-sm font-medium text-foreground">{{ opt.label }}</span>
            <span v-if="opt.description" class="text-xs text-muted-foreground">
              {{ opt.description }}
            </span>
          </div>
        </button>
      </div>

      <!-- Custom answer -->
      <div class="mt-3 flex gap-2">
        <Input
          v-model="customAnswer"
          :disabled="disabled"
          placeholder="Type a custom answer..."
          class="h-8 text-xs"
          @keydown="handleKeydown"
        />
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 shrink-0 rounded-full border border-border interactive-press"
          :disabled="disabled || !customAnswer.trim()"
          @click="submitCustom"
        >
          <ArrowUp class="h-3.5 w-3.5 text-ai-from" />
        </Button>
      </div>
    </div>
  </div>
</template>

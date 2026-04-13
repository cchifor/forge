<script setup lang="ts">
import { Sparkles } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/shared/ui/tooltip'
import { useAiChat } from '../composables/useAiChat'

const { toggleChat, chatOpen } = useAiChat()

const isMac = typeof navigator !== 'undefined' && navigator.userAgent.includes('Mac')
const shortcutLabel = isMac ? '\u2318J' : 'Ctrl+J'
</script>

<template>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger as-child>
        <Button
          variant="ghost"
          class="gap-1.5 interactive-press"
          :class="chatOpen ? 'text-primary' : ''"
          @click="toggleChat"
        >
          <Sparkles class="h-4 w-4 text-ai-from" />
          <span class="hidden text-sm sm:inline">
            {{ chatOpen ? 'Close AI' : 'Ask AI' }}
          </span>
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        Toggle AI Chat ({{ shortcutLabel }})
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>

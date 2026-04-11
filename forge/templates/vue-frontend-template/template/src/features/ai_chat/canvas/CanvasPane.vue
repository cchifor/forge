<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, X, Sparkles } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import { useCanvas } from '../composables/useCanvas'
import { useAiChat } from '../composables/useAiChat'
import { resolveCanvasComponent } from './registry'
import { AgUiEngine, McpExtEngine } from '../workspace/engines'
import type { WorkspaceAction } from '../types'

const { canvasActivity, clearCanvas } = useCanvas()
const { sendMessage, respondToPrompt } = useAiChat()

const resolved = computed(() => {
  if (!canvasActivity.value) return null
  return resolveCanvasComponent(canvasActivity.value.activityType)
})

function handleAction(action: WorkspaceAction) {
  if (action.type === 'hitl_response') {
    respondToPrompt(action.data.answer)
  } else if (action.type === 'mcp_tool_call') {
    sendMessage(`[MCP Tool Call] ${action.data.toolName}: ${JSON.stringify(action.data.args)}`)
  } else {
    sendMessage(JSON.stringify(action))
  }
}
</script>

<template>
  <div v-if="canvasActivity" class="flex h-full flex-col overflow-hidden bg-background">
    <!-- Header -->
    <div class="flex h-12 shrink-0 items-center justify-between border-b px-4">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-full ai-gradient">
          <Sparkles class="h-3.5 w-3.5 text-white" />
        </div>
        <span class="text-sm font-medium">
          {{ canvasActivity.engine === 'mcp-ext' ? 'Extension' : resolved?.label || 'Canvas' }}
        </span>
      </div>
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8 interactive-press"
        @click="clearCanvas"
      >
        <X class="h-4 w-4" />
      </Button>
    </div>

    <!-- Content: engine router -->
    <div :class="canvasActivity.engine === 'mcp-ext' ? 'flex-1' : 'flex-1 overflow-auto'">
      <AgUiEngine
        v-if="canvasActivity.engine === 'ag-ui'"
        :activity="canvasActivity"
        :state="{}"
        @action="handleAction"
      />
      <McpExtEngine
        v-else-if="canvasActivity.engine === 'mcp-ext'"
        :activity="canvasActivity"
        :state="{}"
        @action="handleAction"
      />
    </div>
  </div>
</template>

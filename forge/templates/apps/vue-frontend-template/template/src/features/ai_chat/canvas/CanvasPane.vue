<script setup lang="ts">
import { computed } from 'vue'
import { X, Sparkles } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import CanvasError from './CanvasError.vue'
import { useCanvas } from '../composables/useCanvas'
import { useAiChat } from '../composables/useAiChat'
import { useAgentClient } from '../composables/useAgentClient'
import { resolveCanvasComponent } from './registry'
import { AgUiEngine, McpExtEngine } from '../workspace/engines'
import type { WorkspaceAction } from '../types'

const { canvasActivity, clearCanvas } = useCanvas()
const { sendMessage, respondToPrompt } = useAiChat()
const { respondToFrontendTool } = useAgentClient()

const resolved = computed(() => {
  if (!canvasActivity.value) return null
  return resolveCanvasComponent(canvasActivity.value.activityType)
})

function handleAction(action: WorkspaceAction) {
  // Frontend-tool round-trip: the canvas renderers (form / table / approval)
  // emit `{ type, toolCallId, data }`. When a toolCallId is present we resolve
  // the deferred AG-UI tool call and let the agent resume, instead of routing
  // the action through the legacy HITL / sendMessage paths. `toolCallId` is not
  // on the shared WorkspaceAction type (the renderers add it), so read it off
  // the action defensively.
  const toolCallId = (action as { toolCallId?: string }).toolCallId
  if (toolCallId) {
    const data = (action as { data?: unknown }).data
    switch (action.type) {
      case 'form_submit':
      case 'table_submit':
      case 'approval_decision':
        respondToFrontendTool(toolCallId, JSON.stringify(data))
        return
      case 'form_cancel':
        respondToFrontendTool(toolCallId, JSON.stringify({ cancelled: true }))
        return
      default:
        // Unknown tool-tagged action — fall through to the legacy handling.
        break
    }
  }
  if (action.type === 'hitl_response') {
    respondToPrompt(action.data.answer)
  } else if (action.type === 'form_submit') {
    respondToPrompt(JSON.stringify(action.data.values))
    clearCanvas()
  } else if (action.type === 'form_cancel') {
    respondToPrompt('[cancelled]')
    clearCanvas()
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

    <!-- Content: engine router. Wrapped in <CanvasError> so a crashing
         canvas component renders a fallback card instead of unmounting
         the entire pane (v2 Theme 8-C2). -->
    <div :class="canvasActivity.engine === 'mcp-ext' ? 'flex-1' : 'flex-1 overflow-auto'">
      <CanvasError :component-name="resolved?.label || canvasActivity.activityType">
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
      </CanvasError>
    </div>
  </div>
</template>

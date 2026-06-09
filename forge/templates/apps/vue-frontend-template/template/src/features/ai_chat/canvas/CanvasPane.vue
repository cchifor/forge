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

// Closing the canvas while a deferred frontend tool is pending must RESOLVE the
// tool call (as cancelled) so the agent isn't left waiting on an open deferred
// call. respondToFrontendTool clears the canvas + resumes the run; for a
// non-tool canvas (e.g. a backend ACTIVITY_SNAPSHOT) just clear it.
function closeCanvas() {
  const toolCallId = (canvasActivity.value?.content as { _toolCallId?: string } | undefined)
    ?._toolCallId
  if (toolCallId) {
    respondToFrontendTool(toolCallId, JSON.stringify({ cancelled: true }))
  } else {
    clearCanvas()
  }
}

function handleAction(action: WorkspaceAction) {
  // Frontend-tool round-trip: the canvas renderers (form / table / approval)
  // emit `{ type, toolCallId, data }`. When a toolCallId is present we resolve
  // the deferred AG-UI tool call and let the agent resume, instead of routing
  // the action through the legacy HITL / sendMessage paths.
  if (action.toolCallId) {
    switch (action.type) {
      case 'form_submit':
        // The tool's result is the submitted VALUES (per the tool contract),
        // not the {values} wrapper.
        respondToFrontendTool(
          action.toolCallId,
          JSON.stringify(action.data?.values ?? action.data),
        )
        return
      case 'table_submit':
      case 'approval_decision':
        respondToFrontendTool(action.toolCallId, JSON.stringify(action.data))
        return
      case 'form_cancel':
        respondToFrontendTool(action.toolCallId, JSON.stringify({ cancelled: true }))
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
        @click="closeCanvas"
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

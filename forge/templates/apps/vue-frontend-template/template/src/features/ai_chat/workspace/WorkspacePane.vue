<script setup lang="ts">
import { computed } from 'vue'
import { X, Sparkles } from 'lucide-vue-next'
import { Button } from '@/shared/ui/button'
import { useWorkspace } from '../composables/useWorkspace'
import { useAiChat } from '../composables/useAiChat'
import { resolveWorkspaceComponent } from './registry'
import { AgUiEngine, McpExtEngine } from './engines'
import type { WorkspaceAction } from '../types'

const { currentActivity, hasActivity, clearActivity } = useWorkspace()
const { sendMessage, respondToPrompt } = useAiChat()

const resolved = computed(() => {
  if (!currentActivity.value) return null
  return resolveWorkspaceComponent(currentActivity.value.activityType)
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
  <div v-if="hasActivity && currentActivity" class="flex h-full flex-col overflow-hidden bg-background">
    <!-- Header -->
    <div class="flex h-14 shrink-0 items-center justify-between border-b px-4">
      <div class="flex items-center gap-2">
        <div class="flex h-7 w-7 items-center justify-center rounded-full ai-gradient">
          <Sparkles class="h-3.5 w-3.5 text-white" />
        </div>
        <span class="text-sm font-medium">
          {{ currentActivity.engine === 'mcp-ext' ? 'Extension' : resolved?.label || 'Activity' }}
        </span>
      </div>
      <Button
        variant="ghost"
        size="icon"
        class="h-8 w-8 interactive-press"
        @click="clearActivity"
      >
        <X class="h-4 w-4" />
      </Button>
    </div>

    <!-- Content: engine router -->
    <div class="flex-1 overflow-auto scrollbar-thin">
      <AgUiEngine
        v-if="currentActivity.engine === 'ag-ui'"
        :activity="currentActivity"
        :state="{}"
        @action="handleAction"
      />
      <McpExtEngine
        v-else-if="currentActivity.engine === 'mcp-ext'"
        :activity="currentActivity"
        :state="{}"
        @action="handleAction"
      />
    </div>
  </div>

  <!-- Empty state -->
  <div v-else class="flex h-full flex-col items-center justify-center gap-4 p-8 text-center">
    <div class="flex h-16 w-16 items-center justify-center rounded-full bg-muted">
      <Sparkles class="h-8 w-8 text-muted-foreground" />
    </div>
    <p class="max-w-xs text-sm text-muted-foreground">
      Workspace will appear when the agent needs your input.
    </p>
  </div>
</template>

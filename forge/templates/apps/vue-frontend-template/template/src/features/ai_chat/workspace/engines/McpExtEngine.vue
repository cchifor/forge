<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge'
import { mountMcpExtBridge, type MountMcpExtBridgeHandle } from '../../canvas-core/mcp_bridge'
import type { WorkspaceActivity, AgentState } from '../../types'

const props = defineProps<{
  activity: WorkspaceActivity
  state?: AgentState
}>()

const emit = defineEmits<{
  action: [action: { type: string; data: Record<string, any> }]
}>()

const iframeRef = ref<HTMLIFrameElement | null>(null)
let handle: MountMcpExtBridgeHandle | null = null

// The upstream @modelcontextprotocol/ext-apps AppBridge API is version-specific;
// canvas-core's mountMcpExtBridge owns the construct/connect/teardown lifecycle
// (constructor-injected so canvas-core stays free of the upstream dep). The
// template just wires the inbound events to component emits.
onMounted(() => {
  const iframe = iframeRef.value
  if (!iframe?.contentWindow) return
  handle = mountMcpExtBridge({
    appBridgeCtor: AppBridge,
    transportCtor: PostMessageTransport,
    iframe,
    identity: { name: props.activity.activityType || 'mcp-app', version: '1.0.0' },
    capabilities: { openLinks: {}, logging: {} },
    context: {
      hostContext: {
        theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
        displayMode: 'inline',
      },
    },
    callbacks: {
      onInitialized: ({ sendToolInput }) => {
        sendToolInput(props.activity.content.initialContext || props.activity.content)
      },
      onMessage: (msg) => {
        if (msg.content) emit('action', { type: 'mcp_message', data: { text: msg.content } })
      },
      onOpenLink: ({ url }) => {
        window.open(url, '_blank', 'noopener,noreferrer')
      },
      onSizeChange: ({ height }) => {
        if (height && iframe) iframe.style.height = `${height}px`
      },
      onToolCall: async ({ name, arguments: args }) => {
        emit('action', { type: 'mcp_tool_call', data: { toolName: name, args: args || {} } })
        return {}
      },
    },
    html: props.activity.content.html,
    csp: props.activity.content.csp,
    permissions: props.activity.content.permissions,
  })
})

// Re-send tool input when activity content changes.
watch(
  () => props.activity.content,
  (newContent) => {
    handle?.sendToolInput(newContent.initialContext || newContent)
  },
  { deep: true },
)

onUnmounted(() => {
  handle?.cleanup()
  handle = null
})

// Expose sendToolResult so parent components can push results back to the app.
function sendToolResult(result: unknown) {
  handle?.sendToolResult(result)
}

defineExpose({ sendToolResult })
</script>

<template>
  <iframe
    ref="iframeRef"
    :src="activity.content.entryUrl"
    sandbox="allow-scripts allow-same-origin allow-forms"
    class="w-full h-full border-0"
    title="MCP Extension"
  />
</template>

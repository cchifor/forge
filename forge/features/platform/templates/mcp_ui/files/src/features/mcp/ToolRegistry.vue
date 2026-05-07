<!--
  MCP tool discovery panel (Vue scaffold for Phase 3.4).

  Fetches GET /mcp/tools and renders each tool with its server badge,
  input-schema preview, and an "Invoke" button that opens the
  ApprovalDialog. Filled-in rendering (forms built from input_schema)
  lands with the full MCP rollout in 1.0.0a3.
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'

interface McpTool {
  server: string
  name: string
  description: string
  input_schema: Record<string, unknown>
}

const tools = ref<McpTool[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    const response = await fetch('/mcp/tools')
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    tools.value = (await response.json()) as McpTool[]
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="tool-registry">
    <h2>Available Tools</h2>
    <p v-if="loading">Loading...</p>
    <p v-else-if="error" class="error">Failed to load tools: {{ error }}</p>
    <p v-else-if="tools.length === 0">No MCP servers configured. See mcp.config.json.</p>
    <ul v-else>
      <li v-for="tool in tools" :key="`${tool.server}:${tool.name}`">
        <span class="server-badge">{{ tool.server }}</span>
        <strong>{{ tool.name }}</strong>
        <p>{{ tool.description }}</p>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.tool-registry ul { list-style: none; padding: 0; }
.tool-registry li { padding: 0.5rem 0; border-bottom: 1px solid var(--border, #e5e7eb); }
.server-badge { display: inline-block; padding: 0.1rem 0.4rem; background: var(--muted, #f3f4f6); border-radius: 0.25rem; font-size: 0.75rem; margin-right: 0.5rem; }
.error { color: var(--destructive, #dc2626); }
</style>

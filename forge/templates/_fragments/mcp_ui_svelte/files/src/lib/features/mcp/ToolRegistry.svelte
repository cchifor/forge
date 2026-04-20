<!--
  MCP tool discovery panel (Svelte 5 scaffold for Phase 3.4).

  Fetches GET /mcp/tools and renders each tool with its server badge +
  approval-mode indicator. Svelte 5 runes ($state, $effect) manage the
  loading/data/error state.
-->
<script lang="ts">
  interface McpTool {
    server: string
    name: string
    description: string
    input_schema: Record<string, unknown>
    approval_mode: 'auto' | 'prompt-once' | 'prompt-every'
  }

  let tools = $state<McpTool[]>([])
  let loading = $state(true)
  let error = $state<string | null>(null)

  $effect(() => {
    let cancelled = false
    async function fetchTools() {
      try {
        const response = await fetch('/mcp/tools')
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const data = (await response.json()) as McpTool[]
        if (!cancelled) tools = data
      } catch (e) {
        if (!cancelled) error = (e as Error).message
      } finally {
        if (!cancelled) loading = false
      }
    }
    void fetchTools()
    return () => {
      cancelled = true
    }
  })
</script>

<section class="tool-registry">
  <h2>Available Tools</h2>
  {#if loading}
    <p>Loading...</p>
  {:else if error}
    <p class="error">Failed to load tools: {error}</p>
  {:else if tools.length === 0}
    <p>No MCP servers configured. See <code>mcp.config.json</code>.</p>
  {:else}
    <ul>
      {#each tools as tool (`${tool.server}:${tool.name}`)}
        <li>
          <span class="server-badge">{tool.server}</span>
          <strong>{tool.name}</strong>
          <span class="mode mode-{tool.approval_mode}">{tool.approval_mode}</span>
          <p>{tool.description}</p>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .tool-registry ul { list-style: none; padding: 0; }
  .tool-registry li { padding: 0.5rem 0; border-bottom: 1px solid var(--border, #e5e7eb); }
  .server-badge { display: inline-block; padding: 0.1rem 0.4rem; background: var(--muted, #f3f4f6); border-radius: 0.25rem; font-size: 0.75rem; margin-right: 0.5rem; }
  .mode { font-size: 0.7rem; padding: 0.1rem 0.3rem; border-radius: 0.25rem; margin-left: 0.5rem; vertical-align: middle; }
  .mode-auto { background: #dcfce7; color: #166534; }
  .mode-prompt-once { background: #fef3c7; color: #854d0e; }
  .mode-prompt-every { background: #fee2e2; color: #991b1b; }
  .error { color: var(--destructive, #dc2626); }
</style>

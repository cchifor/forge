// MCP tools hook — client-side cache + approval-mode enforcement.
//
// Pattern:
//
//   const mcp = useMcpTools()
//   await mcp.refresh()
//   const result = await mcp.invoke({
//     server: 'filesystem',
//     tool: 'read_file',
//     input: { path: '/tmp/hello.txt' },
//     onApprovalRequested: (tool) => showApprovalDialog(tool),
//   })
//
// Svelte 5 runes: state is reactive via $state(); derived sets and
// stable action handles come from the caller.

interface McpTool {
  server: string
  name: string
  description: string
  input_schema: Record<string, unknown>
  approval_mode: 'auto' | 'prompt-once' | 'prompt-every'
}

interface InvokeRequest {
  server: string
  tool: string
  input: Record<string, unknown>
  onApprovalRequested?: (tool: McpTool) => Promise<boolean>
}

type SessionApprovalMap = Map<string, boolean>

export function useMcpTools() {
  const tools = $state<McpTool[]>([])
  const sessionApprovals: SessionApprovalMap = new Map()
  let loaded = false

  async function refresh(): Promise<void> {
    const response = await fetch('/mcp/tools')
    if (!response.ok) throw new Error(`GET /mcp/tools ${response.status}`)
    const fresh = (await response.json()) as McpTool[]
    tools.splice(0, tools.length, ...fresh)
    loaded = true
  }

  async function invoke(req: InvokeRequest): Promise<unknown> {
    if (!loaded) await refresh()
    const tool = tools.find((t) => t.server === req.server && t.name === req.tool)
    if (!tool) throw new Error(`MCP tool not found: ${req.server}:${req.tool}`)

    const key = `${req.server}:${req.tool}`
    const already = sessionApprovals.get(key)
    if (already === false) throw new Error(`user denied tool: ${key}`)

    if (tool.approval_mode !== 'auto' && already !== true) {
      const approved =
        req.onApprovalRequested !== undefined
          ? await req.onApprovalRequested(tool)
          : false
      if (tool.approval_mode === 'prompt-once') sessionApprovals.set(key, approved)
      if (!approved) throw new Error(`user denied tool: ${key}`)
    }

    const response = await fetch('/mcp/invoke', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        server: req.server,
        tool: req.tool,
        input: req.input,
      }),
    })
    if (!response.ok) throw new Error(`POST /mcp/invoke ${response.status}`)
    const payload = (await response.json()) as { ok: boolean; output?: unknown; error?: string }
    if (!payload.ok) throw new Error(payload.error || 'MCP invoke failed')
    return payload.output
  }

  return {
    get tools(): readonly McpTool[] {
      return tools
    },
    refresh,
    invoke,
  }
}

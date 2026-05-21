// MCP tools hook — client-side cache + approval-mode enforcement.
//
// Wire-protocol fix (Pillar B Phase 1 of the architectural improvement plan):
// before this rewrite, `invoke()` POSTed to `/mcp/invoke` with no
// `approval_token`, but the Python backend requires one whenever
// `approval_mode != "auto"` and rejects with HTTP 401 otherwise. Every
// non-auto invocation 401'd; the bug was masked by MCP UI panels being
// stubs nobody routed real traffic through. This implementation:
//
//   1. After the user approves, POST /mcp/approval/mint to get a
//      signed token (HMAC-SHA256, TTL 3600s — see audit.py).
//   2. POST /mcp/invoke with { ...payload, approval_token } so the
//      backend's `verify_approval_token` passes.
//   3. Cache the token per (server, tool, input-hash) for the session
//      so repeated `prompt-once` invocations reuse it until either
//      TTL expiry or the user explicitly resets.
//
// TODO(Pillar B Phase 2): once `@forge/canvas-core` is published, the
// algorithm below becomes:
//
//     import { McpApprovalClient } from '@forge/canvas-core'
//     const client = new McpApprovalClient()
//     await client.invoke({ server, tool, input, approvalMode })
//
// Until then, the inline version below MUST stay byte-for-byte
// equivalent to `McpApprovalClient` so the eventual swap is mechanical
// and the test contract in
// `packages/canvas-core/tests/mcp_approval_client.test.ts` covers
// both.
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

interface CachedToken {
  token: string
  expiresAt: number
}

// Default TTL matches the backend's MCP_APPROVAL_TOKEN_TTL_SECONDS
// (audit.py line 130), minus a 30s safety margin to avoid edge-of-TTL
// races between the client's clock and the backend's.
const APPROVAL_TOKEN_TTL_MS = (3600 - 30) * 1000

function tokenCacheKey(req: { server: string; tool: string; input: Record<string, unknown> }): string {
  return `${req.server}::${req.tool}::${JSON.stringify(req.input)}`
}

export function useMcpTools() {
  const tools = $state<McpTool[]>([])
  const sessionApprovals: SessionApprovalMap = new Map()
  const tokenCache = new Map<string, CachedToken>()
  let loaded = false

  async function refresh(): Promise<void> {
    const response = await fetch('/mcp/tools')
    if (!response.ok) throw new Error(`GET /mcp/tools ${response.status}`)
    const fresh = (await response.json()) as McpTool[]
    tools.splice(0, tools.length, ...fresh)
    loaded = true
  }

  async function mintApprovalToken(req: {
    server: string
    tool: string
    input: Record<string, unknown>
  }): Promise<string> {
    const key = tokenCacheKey(req)
    const cached = tokenCache.get(key)
    if (cached && cached.expiresAt > Date.now()) {
      return cached.token
    }
    const response = await fetch('/mcp/approval/mint', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ server: req.server, tool: req.tool, input: req.input }),
    })
    if (!response.ok) {
      throw new Error(
        `Failed to mint MCP approval token for ${req.server}:${req.tool} ` +
          `(status ${response.status})`,
      )
    }
    const data = (await response.json()) as { token?: unknown }
    if (typeof data.token !== 'string' || data.token === '') {
      throw new Error(`MCP approval mint returned no token for ${req.server}:${req.tool}`)
    }
    tokenCache.set(key, { token: data.token, expiresAt: Date.now() + APPROVAL_TOKEN_TTL_MS })
    return data.token
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

    // Backend gates non-auto modes on `approval_token`; mint then send.
    const body: Record<string, unknown> = {
      server: req.server,
      tool: req.tool,
      input: req.input,
    }
    if (tool.approval_mode !== 'auto') {
      body.approval_token = await mintApprovalToken({
        server: req.server,
        tool: req.tool,
        input: req.input,
      })
    }

    const response = await fetch('/mcp/invoke', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (response.status === 401) {
      // Token was rejected — most likely it expired between mint and
      // invoke, or the backend secret rotated. Evict the cache so the
      // next call re-mints, and surface a clear error so the UI can
      // re-prompt rather than silently retrying.
      tokenCache.delete(tokenCacheKey(req))
      throw new Error(
        `MCP approval token rejected for ${req.server}:${req.tool}. ` +
          `Re-approve to mint a fresh token.`,
      )
    }
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

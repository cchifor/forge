/**
 * Test the wire-protocol bug fix end-to-end against a mocked backend.
 *
 * The Python backend at `forge/features/platform/templates/mcp_server/python/files/src/app/mcp/router.py`
 * 401s on `/mcp/invoke` when `approval_mode != "auto"` and the
 * `approval_token` is missing/invalid. This test fakes that backend
 * and verifies the client mints + presents the token correctly.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  McpApprovalClient,
  McpApprovalRejected,
  type McpInvokeRequest,
} from '../src/index.js'

interface FakeServer {
  fetch: typeof globalThis.fetch
  mintedTokens: string[]
  invokeCalls: Array<{ body: Record<string, unknown>; tokenSeen: string | null }>
  /** Force the next mint to 404. */
  failMint?: 404 | 500
  /** Force the next invoke to 401 (e.g. expired token). */
  failInvokeWith401Once?: boolean
}

function makeFakeServer(opts: { knownTokens?: string[] } = {}): FakeServer {
  const knownTokens = new Set(opts.knownTokens ?? [])
  const server: FakeServer = {
    mintedTokens: [],
    invokeCalls: [],
    fetch: (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.endsWith('/mcp/approval/mint')) {
        if (server.failMint) {
          return new Response(`mint failed: ${server.failMint}`, {
            status: server.failMint,
          })
        }
        const token = `token-${server.mintedTokens.length + 1}`
        server.mintedTokens.push(token)
        knownTokens.add(token)
        return new Response(JSON.stringify({ token }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      if (url.endsWith('/mcp/invoke')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
        const tokenSeen = (body['approval_token'] as string | undefined) ?? null
        server.invokeCalls.push({ body, tokenSeen })
        if (server.failInvokeWith401Once) {
          server.failInvokeWith401Once = false
          return new Response('Approval token missing or invalid. Call /mcp/approval/mint first.', {
            status: 401,
          })
        }
        // auto path: no token required → accept.
        if (tokenSeen === null) {
          return new Response(JSON.stringify({ ok: true, output: 'auto-ok' }), {
            status: 200,
            headers: { 'content-type': 'application/json' },
          })
        }
        if (!knownTokens.has(tokenSeen)) {
          return new Response('Approval token missing or invalid. Call /mcp/approval/mint first.', {
            status: 401,
          })
        }
        return new Response(JSON.stringify({ ok: true, output: 'gated-ok' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response('not found', { status: 404 })
    }) as typeof globalThis.fetch,
  }
  return server
}

const baseReq: McpInvokeRequest = {
  server: 'filesystem',
  tool: 'read_file',
  input: { path: '/etc/hosts' },
  approvalMode: 'prompt-once',
}

describe('McpApprovalClient — wire-bug fix', () => {
  let server: FakeServer
  let now: number

  beforeEach(() => {
    server = makeFakeServer()
    now = 1_000_000
  })

  it('auto mode skips mint and invokes directly', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    const result = await client.invoke({ ...baseReq, approvalMode: 'auto' })
    expect(result).toEqual({ ok: true, output: 'auto-ok' })
    expect(server.mintedTokens).toHaveLength(0)
    expect(server.invokeCalls).toHaveLength(1)
    expect(server.invokeCalls[0]?.tokenSeen).toBeNull()
  })

  it('non-auto mode mints, then invokes with the token (THE bug fix)', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    const result = await client.invoke(baseReq)
    expect(result).toEqual({ ok: true, output: 'gated-ok' })
    expect(server.mintedTokens).toHaveLength(1)
    expect(server.invokeCalls).toHaveLength(1)
    expect(server.invokeCalls[0]?.tokenSeen).toBe(server.mintedTokens[0])
  })

  it('caches the token across invocations of the same (server, tool, input)', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    await client.invoke(baseReq)
    await client.invoke(baseReq)
    expect(server.mintedTokens).toHaveLength(1)
    expect(server.invokeCalls).toHaveLength(2)
    expect(server.invokeCalls.map((c) => c.tokenSeen)).toEqual([
      server.mintedTokens[0],
      server.mintedTokens[0],
    ])
  })

  it('re-mints when the input payload changes (signature would mismatch)', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    await client.invoke(baseReq)
    await client.invoke({ ...baseReq, input: { path: '/etc/passwd' } })
    expect(server.mintedTokens).toHaveLength(2)
  })

  it('re-mints after token TTL expires', async () => {
    const client = new McpApprovalClient({
      fetch: server.fetch,
      now: () => now,
      tokenTtlMs: 1000,
    })
    await client.invoke(baseReq)
    now += 2000
    await client.invoke(baseReq)
    expect(server.mintedTokens).toHaveLength(2)
  })

  it('raises McpApprovalRejected on 401 + evicts the cached token', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    // Prime cache with a valid token.
    await client.invoke(baseReq)
    expect(server.mintedTokens).toHaveLength(1)

    // Now force the next invoke to 401 (e.g. backend rotated its secret).
    server.failInvokeWith401Once = true
    await expect(client.invoke(baseReq)).rejects.toBeInstanceOf(McpApprovalRejected)

    // The cache should have been evicted; next invoke re-mints.
    await client.invoke(baseReq)
    expect(server.mintedTokens).toHaveLength(2)
  })

  it('surfaces clear error when mint endpoint returns 404', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    server.failMint = 404
    await expect(client.invoke(baseReq)).rejects.toThrow(/Failed to mint MCP approval token/)
  })

  it('honours custom baseUrl', async () => {
    const calls: string[] = []
    const wrappedFetch: typeof globalThis.fetch = async (input, init) => {
      calls.push(typeof input === 'string' ? input : input.toString())
      return server.fetch(input, init)
    }
    const client = new McpApprovalClient({
      fetch: wrappedFetch,
      now: () => now,
      baseUrl: 'https://api.example.test/api',
    })
    await client.invoke(baseReq)
    expect(calls).toContain('https://api.example.test/api/mcp/approval/mint')
    expect(calls).toContain('https://api.example.test/api/mcp/invoke')
  })

  it('evict() forces a re-mint on next invoke', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    await client.invoke(baseReq)
    client.evict(baseReq)
    await client.invoke(baseReq)
    expect(server.mintedTokens).toHaveLength(2)
  })

  it('clearCache() drops all tokens', async () => {
    const client = new McpApprovalClient({ fetch: server.fetch, now: () => now })
    await client.invoke(baseReq)
    await client.invoke({ ...baseReq, tool: 'other' })
    client.clearCache()
    await client.invoke(baseReq)
    expect(server.mintedTokens).toHaveLength(3)
  })
})

describe('McpApprovalClient — McpApprovalRejected', () => {
  it('exposes structured fields', () => {
    const err = new McpApprovalRejected({
      server: 'filesystem',
      tool: 'read_file',
      status: 401,
      detail: 'token expired',
    })
    expect(err.name).toBe('McpApprovalRejected')
    expect(err.server).toBe('filesystem')
    expect(err.tool).toBe('read_file')
    expect(err.status).toBe(401)
    expect(err.detail).toBe('token expired')
  })

  it('propagates uncaught fetch failures unchanged', async () => {
    const brokenFetch = vi.fn(async () => {
      throw new TypeError('network down')
    }) as unknown as typeof globalThis.fetch
    const client = new McpApprovalClient({ fetch: brokenFetch })
    await expect(client.invoke(baseReq)).rejects.toThrow('network down')
  })
})

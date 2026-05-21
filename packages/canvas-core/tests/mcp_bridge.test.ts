/**
 * MCP bridge — the typed wrapper around `@modelcontextprotocol/ext-apps/app-bridge`.
 *
 * We don't take a hard dep on the upstream package; tests use an
 * in-process `UpstreamAppBridge` fake to verify wiring.
 */

import { describe, expect, it } from 'vitest'
import {
  createMcpBridge,
  MCP_BRIDGE_AVAILABLE,
  type UpstreamAppBridge,
} from '../src/index.js'

function makeFakeUpstream(): UpstreamAppBridge & {
  toolResultPayload: unknown
  teardownCallCount: number
} {
  const fake: UpstreamAppBridge & {
    toolResultPayload: unknown
    teardownCallCount: number
  } = {
    oninitialized: () => {},
    onmessage: () => {},
    onopenlink: () => {},
    onsizechange: () => {},
    ontoolcall: async () => ({}),
    async connect() {},
    sendToolInput() {},
    sendToolResult(result: unknown) {
      fake.toolResultPayload = result
    },
    async teardownResource() {
      fake.teardownCallCount += 1
    },
    toolResultPayload: undefined,
    teardownCallCount: 0,
  }
  return fake
}

describe('MCP_BRIDGE_AVAILABLE', () => {
  it('is true under jsdom (which provides window)', () => {
    expect(MCP_BRIDGE_AVAILABLE).toBe(true)
  })
})

describe('createMcpBridge', () => {
  it('forwards onToolCall handlers to the upstream', async () => {
    const upstream = makeFakeUpstream()
    const bridge = createMcpBridge(upstream)
    bridge.on({
      onToolCall: async (req) => ({ echo: req.name }),
    })
    const out = await upstream.ontoolcall({ name: 'read_file', arguments: { path: '/x' } })
    expect(out).toEqual({ echo: 'read_file' })
  })

  it('forwards onMessage / onOpenLink / onSizeChange / onInitialized', () => {
    const upstream = makeFakeUpstream()
    const bridge = createMcpBridge(upstream)
    let initCount = 0
    const messages: string[] = []
    const links: string[] = []
    const sizes: number[] = []
    bridge.on({
      onInitialized: () => initCount++,
      onMessage: (msg) => messages.push(msg.content),
      onOpenLink: (req) => links.push(req.url),
      onSizeChange: (size) => sizes.push(size.height),
    })
    upstream.oninitialized()
    upstream.onmessage({ content: 'hi' })
    upstream.onopenlink({ url: 'https://example.test' })
    upstream.onsizechange({ height: 320 })
    expect(initCount).toBe(1)
    expect(messages).toEqual(['hi'])
    expect(links).toEqual(['https://example.test'])
    expect(sizes).toEqual([320])
  })

  it('sendToolResult forwards', () => {
    const upstream = makeFakeUpstream()
    const bridge = createMcpBridge(upstream)
    bridge.sendToolResult({ ok: true, output: 'done' })
    expect(upstream.toolResultPayload).toEqual({ ok: true, output: 'done' })
  })

  it('close calls teardownResource exactly once per call', async () => {
    const upstream = makeFakeUpstream()
    const bridge = createMcpBridge(upstream)
    await bridge.close()
    await bridge.close()
    expect(upstream.teardownCallCount).toBe(2)
  })

  it('on() is partial-application friendly — handlers can be set incrementally', () => {
    const upstream = makeFakeUpstream()
    const bridge = createMcpBridge(upstream)
    let init = 0
    bridge.on({ onInitialized: () => (init += 1) })
    bridge.on({ onMessage: () => {} }) // shouldn't overwrite oninitialized
    upstream.oninitialized()
    expect(init).toBe(1)
  })
})

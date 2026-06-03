import { describe, it, expect } from 'vitest'
import { createMcpBridge, type UpstreamAppBridge } from './mcp_bridge'

/**
 * Round-trip: the bridge adapters must translate the REAL ext-apps@0.4.2 handler
 * signatures (structured params + awaited result objects) onto canvas-core's
 * simplified callbacks. We assign callbacks via createMcpBridge (same
 * adaptInboundHandlers path mountMcpExtBridge uses, minus the web-only guard),
 * capture the adapters the bridge receives, then invoke them with SDK-shaped
 * params and assert the simplified callbacks see the adapted shapes — and that
 * the adapters return the SDK-expected result objects.
 */
function makeFakeBridge() {
  const captured: Record<string, (...args: unknown[]) => unknown> = {}
  const bridge = {
    set oninitialized(cb: (...a: unknown[]) => unknown) {
      captured.oninitialized = cb
    },
    set onmessage(cb: (...a: unknown[]) => unknown) {
      captured.onmessage = cb
    },
    set onopenlink(cb: (...a: unknown[]) => unknown) {
      captured.onopenlink = cb
    },
    set onsizechange(cb: (...a: unknown[]) => unknown) {
      captured.onsizechange = cb
    },
    set oncalltool(cb: (...a: unknown[]) => unknown) {
      captured.oncalltool = cb
    },
    connect: async () => undefined,
    sendToolInput: () => undefined,
    sendToolResult: () => undefined,
    sendSandboxResourceReady: () => undefined,
    teardownResource: async () => undefined,
  } as unknown as UpstreamAppBridge
  return { bridge, captured }
}

describe('mcp bridge adapters (ext-apps@0.4.2 reconciliation)', () => {
  it('adapts onmessage: concatenates text content blocks -> {content} and returns {}', async () => {
    const { bridge, captured } = makeFakeBridge()
    let received: { content: string } | undefined
    createMcpBridge(bridge).on({ onMessage: (msg) => { received = msg } })

    const result = await captured.onmessage({
      role: 'user',
      content: [
        { type: 'text', text: 'hel' },
        { type: 'image', data: 'x' },
        { type: 'text', text: 'lo' },
      ],
    })

    expect(received).toEqual({ content: 'hello' })
    expect(result).toEqual({})
  })

  it('adapts oncalltool (NOT ontoolcall): maps name/arguments + passes the result through', async () => {
    const { bridge, captured } = makeFakeBridge()
    expect(captured.ontoolcall).toBeUndefined() // the SDK setter is oncalltool
    let received: { name: string; arguments: Record<string, unknown> } | undefined
    const toolResult = { content: [{ type: 'text', text: 'done' }] }
    createMcpBridge(bridge).on({
      onToolCall: async (req) => {
        received = req
        return toolResult
      },
    })

    const result = await captured.oncalltool({ name: 'do_thing', arguments: { a: 1 } })

    expect(received).toEqual({ name: 'do_thing', arguments: { a: 1 } })
    expect(result).toEqual(toolResult)
  })

  it('oncalltool defaults to a valid empty CallToolResult when the caller returns nothing', async () => {
    const { bridge, captured } = makeFakeBridge()
    createMcpBridge(bridge).on({ onToolCall: async () => undefined })

    const result = await captured.oncalltool({ name: 'x', arguments: {} })

    // CallToolResult requires `content`; {} would violate the SDK contract.
    expect(result).toEqual({ content: [] })
  })

  it('adapts onopenlink -> {url} and returns {}', async () => {
    const { bridge, captured } = makeFakeBridge()
    let received: { url: string } | undefined
    createMcpBridge(bridge).on({ onOpenLink: (req) => { received = req } })

    const result = await captured.onopenlink({ url: 'https://example.test' })

    expect(received).toEqual({ url: 'https://example.test' })
    expect(result).toEqual({})
  })

  it('adapts onsizechange: omitted height -> 0', () => {
    const { bridge, captured } = makeFakeBridge()
    let received: { width?: number; height: number } | undefined
    createMcpBridge(bridge).on({ onSizeChange: (size) => { received = size } })

    captured.onsizechange({ width: 320 })

    expect(received).toEqual({ width: 320, height: 0 })
  })
})

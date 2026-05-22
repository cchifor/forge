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
  mountMcpExtBridge,
  type AppBridgeCapabilities,
  type AppBridgeContext,
  type AppBridgeIdentity,
  type MountMcpExtBridgeOptions,
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
    sendSandboxResourceReady() {},
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

// --- mountMcpExtBridge ----------------------------------------------------

interface BridgeSpy {
  upstream: ReturnType<typeof makeFakeUpstream> & {
    sandboxReadyArgs: unknown
    sandboxReadyCalls: number
    toolInputArgs: unknown
    constructorArgs: {
      parent: unknown
      identity: AppBridgeIdentity
      capabilities: AppBridgeCapabilities
      context: AppBridgeContext
    } | null
  }
  /** Externally controllable connect resolution. */
  resolveConnect: () => void
  rejectConnect: (reason?: unknown) => void
}

/**
 * Build an `AppBridge` constructor stub that lets the test caller
 * drive when `connect()` resolves. The constructed instance is exposed
 * on `spy.upstream` so the test can also poke handlers (`onmessage`,
 * etc.) and inspect outbound calls (`sendSandboxResourceReady`,
 * `sendToolInput`, `teardownResource`).
 */
function makeAppBridgeCtor(spy: BridgeSpy): MountMcpExtBridgeOptions['appBridgeCtor'] {
  const fake = makeFakeUpstream() as BridgeSpy['upstream']
  fake.sandboxReadyArgs = undefined
  fake.sandboxReadyCalls = 0
  fake.toolInputArgs = undefined
  fake.constructorArgs = null
  fake.sendSandboxResourceReady = (args: {
    html: string
    csp?: string
    permissions?: unknown
  }): void => {
    fake.sandboxReadyArgs = args
    fake.sandboxReadyCalls += 1
  }
  fake.sendToolInput = (args: { arguments: Record<string, unknown> }): void => {
    fake.toolInputArgs = args
  }
  fake.connect = (): Promise<void> =>
    new Promise<void>((resolve, reject) => {
      spy.resolveConnect = resolve
      spy.rejectConnect = reject
    })
  spy.upstream = fake
  spy.resolveConnect = () => {}
  spy.rejectConnect = () => {}

  return class FakeAppBridge {
    constructor(
      parent: unknown,
      identity: AppBridgeIdentity,
      capabilities: AppBridgeCapabilities,
      context: AppBridgeContext,
    ) {
      fake.constructorArgs = { parent, identity, capabilities, context }
      return fake as unknown as FakeAppBridge
    }
  } as unknown as MountMcpExtBridgeOptions['appBridgeCtor']
}

function makeTransportCtor(): MountMcpExtBridgeOptions['transportCtor'] {
  return class FakeTransport {
    constructor(
      public readonly source: Window,
      public readonly target: Window,
    ) {}
  } as unknown as MountMcpExtBridgeOptions['transportCtor']
}

function makeIframe(): HTMLIFrameElement {
  const iframe = document.createElement('iframe')
  document.body.appendChild(iframe)
  return iframe
}

const IDENTITY: AppBridgeIdentity = { name: 'mcp-app', version: '1.0.0' }
const CAPABILITIES: AppBridgeCapabilities = { openLinks: {}, logging: {} }
const CONTEXT: AppBridgeContext = {
  hostContext: { theme: 'light', displayMode: 'inline' },
}

describe('mountMcpExtBridge', () => {
  it('passes identity / capabilities / context through to the AppBridge constructor', () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
    })
    expect(spy.upstream.constructorArgs).toEqual({
      parent: null,
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
    })
    handle.cleanup()
  })

  it('wires onMessage / onOpenLink / onSizeChange / onToolCall to caller callbacks', async () => {
    const spy = {} as BridgeSpy
    const messages: string[] = []
    const links: string[] = []
    const sizes: number[] = []
    const tools: string[] = []

    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {
        onMessage: (msg) => {
          messages.push(msg.content)
        },
        onOpenLink: async (req) => {
          links.push(req.url)
        },
        onSizeChange: (size) => {
          sizes.push(size.height)
        },
        onToolCall: async (req) => {
          tools.push(req.name)
          return { ok: true }
        },
      },
    })

    spy.upstream.onmessage({ content: 'hello' })
    await spy.upstream.onopenlink({ url: 'https://example.test' })
    spy.upstream.onsizechange({ height: 480 })
    const toolResult = await spy.upstream.ontoolcall({
      name: 'read_file',
      arguments: { path: '/x' },
    })

    expect(messages).toEqual(['hello'])
    expect(links).toEqual(['https://example.test'])
    expect(sizes).toEqual([480])
    expect(tools).toEqual(['read_file'])
    expect(toolResult).toEqual({ ok: true })
    handle.cleanup()
  })

  it('onInitialized exposes a sendToolInput handle that forwards arguments to the upstream', () => {
    const spy = {} as BridgeSpy
    let received: { sendToolInput: (i: Record<string, unknown>) => void } | null = null
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {
        onInitialized: (handles) => {
          received = handles
        },
      },
    })

    spy.upstream.oninitialized()
    expect(received).not.toBeNull()
    received!.sendToolInput({ greeting: 'hi' })
    expect(spy.upstream.toolInputArgs).toEqual({ arguments: { greeting: 'hi' } })
    handle.cleanup()
  })

  it('fires sendSandboxResourceReady after connect when html is present', async () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
      html: '<h1>Hi</h1>',
      csp: "default-src 'self'",
      permissions: ['camera'],
    })

    // Resolve the pending connect Promise so the post-connect step runs.
    spy.resolveConnect()
    await Promise.resolve()
    await Promise.resolve()

    expect(spy.upstream.sandboxReadyCalls).toBe(1)
    expect(spy.upstream.sandboxReadyArgs).toEqual({
      html: '<h1>Hi</h1>',
      csp: "default-src 'self'",
      permissions: ['camera'],
    })
    handle.cleanup()
  })

  it('does not fire sendSandboxResourceReady when html is absent', async () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
      // html intentionally omitted
    })

    spy.resolveConnect()
    await Promise.resolve()
    await Promise.resolve()

    expect(spy.upstream.sandboxReadyCalls).toBe(0)
    handle.cleanup()
  })

  it('unmount-during-connect race — cleanup before connect resolves skips sendSandboxResourceReady', async () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
      html: '<h1>Hi</h1>',
    })

    // Caller unmounts while connect() is still pending.
    handle.cleanup()

    spy.resolveConnect()
    await Promise.resolve()
    await Promise.resolve()

    expect(spy.upstream.sandboxReadyCalls).toBe(0)
  })

  it('cleanup() calls teardownResource exactly once even when invoked repeatedly', () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
    })

    handle.cleanup()
    handle.cleanup()
    handle.cleanup()

    expect(spy.upstream.teardownCallCount).toBe(1)
  })

  it('sendToolResult forwards through to the upstream', () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
    })

    handle.sendToolResult({ result: 42 })
    expect(spy.upstream.toolResultPayload).toEqual({ result: 42 })
    handle.cleanup()
  })

  it('sendToolInput from the returned handle swallows errors when upstream throws (bridge not yet connected)', () => {
    const spy = {} as BridgeSpy
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
    })

    spy.upstream.sendToolInput = () => {
      throw new Error('not connected yet')
    }

    expect(() => handle.sendToolInput({ hi: true })).not.toThrow()
    handle.cleanup()
  })

  it('throws descriptively when iframe.contentWindow is null', () => {
    const spy = {} as BridgeSpy
    // Detached iframe — contentWindow is null until added to document.
    const orphan = document.createElement('iframe')
    expect(() =>
      mountMcpExtBridge({
        appBridgeCtor: makeAppBridgeCtor(spy),
        transportCtor: makeTransportCtor(),
        iframe: orphan,
        identity: IDENTITY,
        capabilities: CAPABILITIES,
        context: CONTEXT,
        callbacks: {},
      }),
    ).toThrow(/iframe\.contentWindow is null/)
  })

  // Codex Phase B round 1 follow-up tests:

  it('constructs PostMessageTransport with the iframe contentWindow as both source AND target', () => {
    const spy = {} as BridgeSpy
    let receivedSource: Window | null = null
    let receivedTarget: Window | null = null
    const TransportCtorSpy = class FakeTransport {
      constructor(source: Window, target: Window) {
        receivedSource = source
        receivedTarget = target
      }
    } as unknown as MountMcpExtBridgeOptions['transportCtor']
    const iframe = makeIframe()
    const handle = mountMcpExtBridge({
      appBridgeCtor: makeAppBridgeCtor(spy),
      transportCtor: TransportCtorSpy,
      iframe,
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
    })
    expect(receivedSource).toBe(iframe.contentWindow)
    expect(receivedTarget).toBe(iframe.contentWindow)
    expect(receivedSource).toBe(receivedTarget)
    handle.cleanup()
  })

  it('swallows a rejected connect() promise (no unhandled rejection)', async () => {
    const spy = {} as BridgeSpy
    const RejectingCtor = function (this: BridgeSpy, args: unknown) {
      spy.upstream = {
        constructorArgs: args,
        connect: () => Promise.reject(new Error('hand-shake failed')),
        sendToolInput: () => {},
        sendToolResult: () => {},
        teardownResource: () => Promise.resolve(),
        sendSandboxResourceReady: () => {},
      } as unknown as BridgeSpy['upstream']
      return spy.upstream
    } as unknown as MountMcpExtBridgeOptions['appBridgeCtor']

    const handle = mountMcpExtBridge({
      appBridgeCtor: RejectingCtor,
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
      html: '<p>x</p>',
    })

    // Yield to microtasks so the rejection is delivered.
    await Promise.resolve()
    await Promise.resolve()
    // If the helper didn't .catch(), Node would warn on unhandled
    // rejection. We assert by asserting cleanup is still fine.
    expect(() => handle.cleanup()).not.toThrow()
  })

  it('skips sendSandboxResourceReady when the upstream bridge lacks the method (legacy mock support)', async () => {
    // Simulates a downstream consumer's custom UpstreamAppBridge stub
    // that predates the optional sendSandboxResourceReady method.
    const LegacyCtor = function () {
      return {
        oninitialized: () => {},
        onmessage: () => {},
        onopenlink: () => {},
        onsizechange: () => {},
        ontoolcall: async () => ({}),
        connect: () => Promise.resolve(),
        sendToolInput: () => {},
        sendToolResult: () => {},
        teardownResource: () => Promise.resolve(),
        // NOTE: deliberately no sendSandboxResourceReady.
      }
    } as unknown as MountMcpExtBridgeOptions['appBridgeCtor']

    const handle = mountMcpExtBridge({
      appBridgeCtor: LegacyCtor,
      transportCtor: makeTransportCtor(),
      iframe: makeIframe(),
      identity: IDENTITY,
      capabilities: CAPABILITIES,
      context: CONTEXT,
      callbacks: {},
      html: '<p>x</p>',  // would normally trigger sendSandboxResourceReady
    })
    await Promise.resolve()
    await Promise.resolve()
    // No TypeError surfaced; cleanup runs.
    expect(() => handle.cleanup()).not.toThrow()
  })
})

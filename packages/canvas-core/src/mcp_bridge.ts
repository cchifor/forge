/**
 * Typed wrapper around `@modelcontextprotocol/ext-apps/app-bridge`.
 *
 * Extracted from `forge/templates/apps/vue-frontend-template/template/src/features/ai_chat/workspace/engines/McpExtEngine.vue`
 * (Vue is the only stack that today mounts the iframe + bridge; Svelte
 * stubs it and Flutter has no DOM). This module gives all three a
 * single source of truth for the bridge protocol so per-stack engines
 * are pure adapters.
 *
 * Why types rather than re-export the upstream package: the upstream
 * `AppBridge` ships as a JS class with loose generic types — typing
 * the message / tool-call / open-link / size-change handlers in the
 * forge canvas vocabulary catches drift at compile time when the
 * upstream protocol moves.
 *
 * This module is **web-only by contract** (postMessage / iframe). The
 * Flutter `mcp_ext_engine.dart` keeps a no-op stub; we encode this in
 * the {@link MCP_BRIDGE_AVAILABLE} flag rather than crashing at runtime.
 */

export interface AppBridgeIdentity {
  /** Human-readable name of the embedding app (shown in dev tools). */
  name: string
  /** Semver — bump on breaking host-context changes. */
  version: string
}

export interface AppBridgeCapabilities {
  /** Whitelist for `bridge.onopenlink` — empty {} means deny-all. */
  openLinks?: Record<string, unknown>
  /** Bridge-side logging config (delegated to the upstream package). */
  logging?: Record<string, unknown>
}

export interface AppBridgeContext {
  hostContext: {
    theme?: 'light' | 'dark' | 'system'
    displayMode?: 'inline' | 'modal' | 'overlay'
    [extra: string]: unknown
  }
}

export interface ToolCallRequest {
  name: string
  arguments: Record<string, unknown>
}

export interface OpenLinkRequest {
  url: string
}

export interface IframeSizeChange {
  height: number
  width?: number
}

export interface BridgeMessage {
  content: string
  /** Optional structured metadata (e.g. message origin id, role). */
  meta?: Record<string, unknown>
}

/**
 * Minimum surface the host's adapter needs from the upstream
 * `@modelcontextprotocol/ext-apps/app-bridge`. We don't take a hard
 * dep on the package here so canvas-core stays framework-agnostic and
 * Vite-tree-shakable; the per-stack adapter constructs the actual
 * `AppBridge` and passes it in via {@link createMcpBridge}.
 */
export interface UpstreamAppBridge {
  oninitialized: () => void
  onmessage: (msg: BridgeMessage) => void | Promise<void>
  onopenlink: (req: OpenLinkRequest) => void | Promise<void>
  onsizechange: (size: IframeSizeChange) => void
  ontoolcall: (req: ToolCallRequest) => Promise<unknown>
  connect(transport: unknown): Promise<void>
  sendToolInput(args: { arguments: Record<string, unknown> }): void
  sendToolResult(result: unknown): void
  /**
   * Push the sandbox resource (HTML + CSP + permissions) into the
   * iframe once the bridge has connected. Only the iframe-hosted
   * `sandbox-resource` MCP-ext flow uses this; pure `entryUrl`
   * activities skip it.
   */
  sendSandboxResourceReady(args: {
    html: string
    csp?: string
    permissions?: unknown
  }): void
  /** Tear down + free the bridge. Idempotent. */
  teardownResource(args: Record<string, unknown>): Promise<void>
}

export interface McpBridgeHandlers {
  onInitialized?: () => void
  onMessage?: (msg: BridgeMessage) => void | Promise<void>
  onOpenLink?: (req: OpenLinkRequest) => void | Promise<void>
  onSizeChange?: (size: IframeSizeChange) => void
  /**
   * Returns the tool's result payload (whatever shape your backend
   * expects). The bridge round-trips it back to the iframe.
   */
  onToolCall?: (req: ToolCallRequest) => Promise<unknown>
}

export interface McpBridge {
  /** Forward an inbound iframe handler set to the upstream bridge. */
  on(handlers: McpBridgeHandlers): void
  /** Resolve a pending tool call with its result payload. */
  sendToolResult(result: unknown): void
  /** Disconnect and free the bridge. Idempotent. */
  close(): Promise<void>
}

/**
 * `true` when the runtime can host an iframe-based MCP-ext bridge
 * (browser / Electron / webview). Flutter / CLI Dart consumers set
 * this to `false` so their `McpExtEngine` short-circuits to a no-op
 * UI rather than throwing on the missing global.
 */
export const MCP_BRIDGE_AVAILABLE: boolean =
  typeof globalThis !== 'undefined' && typeof (globalThis as { window?: unknown }).window !== 'undefined'

/**
 * Wrap an upstream `AppBridge` in the canvas-core typed interface.
 *
 * Per-stack adapters look like:
 *
 *   import { AppBridge } from '@modelcontextprotocol/ext-apps/app-bridge'
 *   import { createMcpBridge } from '@forge/canvas-core'
 *
 *   const upstream = new AppBridge(null, identity, capabilities, ctx)
 *   const bridge = createMcpBridge(upstream)
 *   bridge.on({ onToolCall: async (req) => await invokeTool(req) })
 */
export function createMcpBridge(upstream: UpstreamAppBridge): McpBridge {
  return {
    on(handlers: McpBridgeHandlers): void {
      if (handlers.onInitialized) upstream.oninitialized = handlers.onInitialized
      if (handlers.onMessage) upstream.onmessage = handlers.onMessage
      if (handlers.onOpenLink) upstream.onopenlink = handlers.onOpenLink
      if (handlers.onSizeChange) upstream.onsizechange = handlers.onSizeChange
      if (handlers.onToolCall) upstream.ontoolcall = handlers.onToolCall
    },
    sendToolResult(result: unknown): void {
      upstream.sendToolResult(result)
    },
    async close(): Promise<void> {
      await upstream.teardownResource({})
    },
  }
}

/**
 * Constructor injection for the upstream `AppBridge` class. The shape
 * matches `new AppBridge(parent, identity, capabilities, context)` from
 * `@modelcontextprotocol/ext-apps/app-bridge`; canvas-core stays free
 * of that dep by accepting the class as a parameter.
 */
export type AppBridgeConstructor = new (
  parent: unknown,
  identity: AppBridgeIdentity,
  capabilities: AppBridgeCapabilities,
  context: AppBridgeContext,
) => UpstreamAppBridge

/**
 * Constructor injection for the upstream `PostMessageTransport`. The
 * shape mirrors `new PostMessageTransport(sourceWindow, targetWindow)`
 * from the upstream package.
 */
export type PostMessageTransportConstructor = new (
  source: Window,
  target: Window,
) => unknown

/** Caller callbacks for inbound iframe events. */
export interface MountMcpExtBridgeCallbacks {
  /**
   * Fires once on upstream `oninitialized`. Templates typically use
   * the supplied `sendToolInput` handle to push the initial activity
   * context into the iframe.
   */
  onInitialized?: (handles: {
    sendToolInput: (input: Record<string, unknown>) => void
  }) => void
  onMessage?: (msg: BridgeMessage) => void | Promise<void>
  onOpenLink?: (req: OpenLinkRequest) => void | Promise<void>
  onSizeChange?: (size: IframeSizeChange) => void
  /**
   * Returns the tool's result payload (whatever shape the host
   * expects). The bridge round-trips it back to the iframe.
   */
  onToolCall?: (req: ToolCallRequest) => Promise<unknown>
}

/**
 * Options for {@link mountMcpExtBridge}. Constructor-injection keeps
 * canvas-core free of the upstream `@modelcontextprotocol/ext-apps`
 * dep; the template (which already imports `AppBridge` +
 * `PostMessageTransport` for its own engine) passes them in.
 */
export interface MountMcpExtBridgeOptions {
  /** `AppBridge` class from `@modelcontextprotocol/ext-apps/app-bridge`. */
  appBridgeCtor: AppBridgeConstructor
  /** `PostMessageTransport` class from the same upstream package. */
  transportCtor: PostMessageTransportConstructor
  /**
   * The iframe element to bind. Must already be in the DOM and have a
   * non-null `contentWindow` at mount time — the helper throws
   * descriptively if either fails.
   */
  iframe: HTMLIFrameElement
  identity: AppBridgeIdentity
  capabilities: AppBridgeCapabilities
  context: AppBridgeContext
  callbacks: MountMcpExtBridgeCallbacks
  /**
   * If set, the helper calls `sendSandboxResourceReady({html, csp,
   * permissions})` once the bridge has connected. Omit for pure
   * `entryUrl` activities.
   */
  html?: string
  csp?: string
  permissions?: unknown
}

/** Handles returned from {@link mountMcpExtBridge}. */
export interface MountMcpExtBridgeHandle {
  /**
   * Tear the bridge down. Idempotent. Also flips an internal cancel
   * flag so an in-flight `connect()` resolution will skip the
   * post-connect `sendSandboxResourceReady` (unmount-during-connect
   * race guard mirrored from the template implementations).
   */
  cleanup(): void
  /**
   * Push fresh tool input to the iframe. Swallows errors because the
   * bridge may not yet have connected — callers (e.g. a Vue watcher
   * or Svelte `$effect`) routinely fire this before the first
   * `oninitialized`.
   */
  sendToolInput(input: Record<string, unknown>): void
  /** Resolve a pending tool call with its result payload. */
  sendToolResult(result: unknown): void
}

/**
 * Mount the upstream `AppBridge` against an iframe and wire the five
 * inbound event handlers to caller callbacks. Consolidates the inline
 * MCP-ext mount logic from
 * `forge/templates/apps/vue-frontend-template/.../McpExtEngine.vue`
 * and
 * `forge/templates/apps/svelte-frontend-template/.../McpExtEngine.svelte`
 * (Pillar B Phase 4) into a single reusable helper. Both templates
 * will migrate to this helper in a follow-up PR; this PR just makes
 * the helper available.
 *
 * Web-only by contract — uses iframe + postMessage. Throws if called
 * when {@link MCP_BRIDGE_AVAILABLE} is `false` so non-web callers
 * (Flutter, CLI Dart) get a fast, descriptive error instead of a
 * `ReferenceError: window is not defined`.
 *
 * **Unmount-during-connect race.** `bridge.connect(transport)` returns
 * a Promise. If the host unmounts the component (calls `cleanup()`)
 * before the Promise resolves, the post-connect
 * `sendSandboxResourceReady` would otherwise fire into a torn-down
 * bridge. The helper tracks a `cancelled` flag flipped by
 * `cleanup()` and consulted at the connect callsite before firing
 * the post-connect step. This mirrors the explicit `if (bridge !==
 * localBridge) return` guard in the Svelte engine.
 */
export function mountMcpExtBridge(
  opts: MountMcpExtBridgeOptions,
): MountMcpExtBridgeHandle {
  if (!MCP_BRIDGE_AVAILABLE) {
    throw new Error(
      'mountMcpExtBridge is web-only — call requires window + iframe. ' +
        'On non-web platforms (Flutter, CLI Dart), gate the call with ' +
        'MCP_BRIDGE_AVAILABLE and render a no-op UI instead.',
    )
  }

  const {
    appBridgeCtor,
    transportCtor,
    iframe,
    identity,
    capabilities,
    context,
    callbacks,
    html,
    csp,
    permissions,
  } = opts

  const contentWindow = iframe.contentWindow as Window | null
  if (!contentWindow) {
    throw new Error(
      'mountMcpExtBridge: iframe.contentWindow is null — the iframe must ' +
        'be attached to the document before mounting the bridge.',
    )
  }

  const bridge = new appBridgeCtor(null, identity, capabilities, context)
  let cancelled = false
  let teardownCalled = false

  const sendToolInput = (input: Record<string, unknown>): void => {
    try {
      bridge.sendToolInput({ arguments: input })
    } catch {
      // Bridge may not yet have connected. Templates routinely fire
      // tool input from a reactive watcher before `oninitialized`.
    }
  }

  bridge.oninitialized = (): void => {
    callbacks.onInitialized?.({ sendToolInput })
  }
  if (callbacks.onMessage) bridge.onmessage = callbacks.onMessage
  if (callbacks.onOpenLink) bridge.onopenlink = callbacks.onOpenLink
  if (callbacks.onSizeChange) bridge.onsizechange = callbacks.onSizeChange
  if (callbacks.onToolCall) bridge.ontoolcall = callbacks.onToolCall

  const transport = new transportCtor(contentWindow, contentWindow)

  void bridge.connect(transport).then(() => {
    if (cancelled) return
    if (typeof html === 'string') {
      bridge.sendSandboxResourceReady({ html, csp, permissions })
    }
  })

  return {
    cleanup(): void {
      cancelled = true
      if (teardownCalled) return
      teardownCalled = true
      void bridge.teardownResource({}).catch(() => {
        // Swallow — teardown errors during unmount are not actionable.
      })
    },
    sendToolInput,
    sendToolResult(result: unknown): void {
      bridge.sendToolResult(result)
    },
  }
}

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

/**
 * Smoke tests for `@forge/canvas-svelte` public exports.
 *
 * Mirrors `packages/canvas-vue/tests/index.test.ts` — see that file's
 * docstring for the rationale (workspace dep resolution + backwards-
 * compat WebSocket client + canvas-core re-export check).
 */

// We import from the component-free `protocol` sub-entry (for the
// canvas-core re-exports) and from `./ag_ui_client` directly (for the
// WebSocket AgUiClient) so vitest doesn't try to preprocess the
// `.svelte` files in `./components/`. The full `@forge/canvas-svelte`
// surface from `index.ts` includes both — see `protocol.ts` for the
// rationale.
import { describe, expect, it } from 'vitest'
import { AgUiClient } from '../src/ag_ui_client'
import {
  EMPTY_CHAT_SNAPSHOT,
  McpApprovalClient,
  McpApprovalRejected,
  parseEvent,
  reduce,
  SseAgUiClient,
  createMcpBridge,
  MCP_BRIDGE_AVAILABLE,
} from '../src/protocol'
import type {
  AgUiEvent,
  ChatStateSnapshot,
  McpInvokeRequest,
  SseAgUiClientOptions,
} from '../src/protocol'

describe('canvas-svelte: WebSocket AgUiClient kept', () => {
  it('AgUiClient is still exported under its historical name', () => {
    expect(typeof AgUiClient).toBe('function')
    expect(
      () =>
        new AgUiClient({
          url: 'ws://test',
          parser: () => null,
          onEvent: () => {},
        }),
    ).not.toThrow()
  })
})

describe('canvas-svelte: canvas-core re-exports resolve', () => {
  it('reducer + snapshot + event helpers come through', () => {
    expect(typeof reduce).toBe('function')
    expect(typeof parseEvent).toBe('function')
    expect(EMPTY_CHAT_SNAPSHOT).toMatchObject({
      messages: [],
      isRunning: false,
      error: null,
    })
  })

  it('McpApprovalClient is the new wire-bug-fix surface', () => {
    expect(typeof McpApprovalClient).toBe('function')
    expect(typeof McpApprovalRejected).toBe('function')
    const client = new McpApprovalClient()
    expect(client).toBeInstanceOf(McpApprovalClient)
  })

  it('SseAgUiClient is namespaced separately from the WS AgUiClient', () => {
    expect(typeof SseAgUiClient).toBe('function')
    expect(SseAgUiClient).not.toBe(AgUiClient)
  })

  it('MCP bridge helpers come through', () => {
    expect(typeof createMcpBridge).toBe('function')
    expect(typeof MCP_BRIDGE_AVAILABLE).toBe('boolean')
  })
})

describe('canvas-svelte: reducer round-trip via re-export', () => {
  it('runs a small RUN_STARTED → TEXT_MESSAGE_START → TEXT_MESSAGE_CONTENT chain', () => {
    const events: AgUiEvent[] = [
      { type: 'RUN_STARTED' },
      { type: 'TEXT_MESSAGE_START', messageId: 'm1', role: 'assistant' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: 'hello' },
    ]
    const final: ChatStateSnapshot = events.reduce(reduce, EMPTY_CHAT_SNAPSHOT)
    expect(final.isRunning).toBe(true)
    expect(final.messages).toHaveLength(1)
    expect(final.messages[0]?.content).toBe('hello')
  })
})

describe('canvas-svelte: type re-exports compile', () => {
  it('McpInvokeRequest + SseAgUiClientOptions are usable as type hints', () => {
    const req: McpInvokeRequest = {
      server: 'filesystem',
      tool: 'read_file',
      input: { path: '/etc/hosts' },
      approvalMode: 'auto',
    }
    const opts: SseAgUiClientOptions<AgUiEvent> = {
      url: 'https://test/agent',
      parser: parseEvent,
      onEvent: () => {},
    }
    expect(req.approvalMode).toBe('auto')
    expect(opts.url).toBe('https://test/agent')
  })
})

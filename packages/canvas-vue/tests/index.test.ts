/**
 * Smoke tests for `@forge/canvas-vue` public exports.
 *
 * Two things to lock in:
 *
 *   1. The canvas-core re-exports actually resolve through the
 *      workspace dep. A missing or misconfigured workspace would
 *      surface here as a `Cannot find module` import error rather
 *      than as a silent runtime hole at template-render time.
 *   2. The existing WebSocket `AgUiClient` is still exported under
 *      its historical name (no breaking rename for existing consumers).
 *
 * Vitest is declared in package.json but has no tests today; this is
 * the first file. Future canvas-vue tests can use this as the seed
 * pattern.
 */

import { describe, expect, it } from 'vitest'
import {
  AgUiClient,
  EMPTY_CHAT_SNAPSHOT,
  McpApprovalClient,
  McpApprovalRejected,
  parseEvent,
  reduce,
  SseAgUiClient,
  createMcpBridge,
  MCP_BRIDGE_AVAILABLE,
} from '../src/index'
import type {
  AgUiEvent,
  ChatStateSnapshot,
  McpInvokeRequest,
  SseAgUiClientOptions,
} from '../src/index'

describe('canvas-vue: WebSocket AgUiClient kept', () => {
  it('AgUiClient is still exported under its historical name', () => {
    expect(typeof AgUiClient).toBe('function')
    // Constructor sanity — no actual WS open in test env.
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

describe('canvas-vue: canvas-core re-exports resolve', () => {
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

describe('canvas-vue: reducer round-trip via re-export', () => {
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

describe('canvas-vue: type re-exports compile', () => {
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

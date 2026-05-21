/**
 * Reducer parity with the Dart reference.
 *
 * Each test mirrors a behaviour exercised by the Dart suite at
 * `packages/forge-canvas-dart/test/agent_state_reducer_test.dart` so a
 * regression on either side surfaces in the other's CI.
 */

import { describe, expect, it } from 'vitest'
import {
  EMPTY_CHAT_SNAPSHOT,
  reduce,
  type AgUiEvent,
  type ChatStateSnapshot,
} from '../src/index.js'

describe('reduce — run lifecycle', () => {
  it('RUN_STARTED clears any stale error', () => {
    const s0: ChatStateSnapshot = { ...EMPTY_CHAT_SNAPSHOT, error: 'boom' }
    const s1 = reduce(s0, { type: 'RUN_STARTED' })
    expect(s1.isRunning).toBe(true)
    expect(s1.error).toBeNull()
  })

  it('RUN_FINISHED flips isRunning without touching error', () => {
    const s0: ChatStateSnapshot = { ...EMPTY_CHAT_SNAPSHOT, isRunning: true, error: null }
    const s1 = reduce(s0, { type: 'RUN_FINISHED' })
    expect(s1.isRunning).toBe(false)
    expect(s1.error).toBeNull()
  })

  it('RUN_ERROR sets error + stops the run', () => {
    const s0: ChatStateSnapshot = { ...EMPTY_CHAT_SNAPSHOT, isRunning: true }
    const s1 = reduce(s0, { type: 'RUN_ERROR', message: 'rate limit' })
    expect(s1.isRunning).toBe(false)
    expect(s1.error).toBe('rate limit')
  })
})

describe('reduce — text messages', () => {
  it('appends a streaming message on TEXT_MESSAGE_START', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'TEXT_MESSAGE_START',
      messageId: 'm1',
      role: 'assistant',
    })
    expect(s1.messages).toHaveLength(1)
    expect(s1.messages[0]).toMatchObject({ id: 'm1', role: 'assistant', isStreaming: true })
  })

  it('appends deltas on TEXT_MESSAGE_CONTENT', () => {
    const events: AgUiEvent[] = [
      { type: 'TEXT_MESSAGE_START', messageId: 'm1', role: 'assistant' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: 'Hello' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: ', world' },
      { type: 'TEXT_MESSAGE_END', messageId: 'm1' },
    ]
    const final = events.reduce(reduce, EMPTY_CHAT_SNAPSHOT)
    expect(final.messages[0]?.content).toBe('Hello, world')
    expect(final.messages[0]?.isStreaming).toBe(false)
  })

  it('CONTENT with unknown messageId falls back to the last message', () => {
    const events: AgUiEvent[] = [
      { type: 'TEXT_MESSAGE_START', messageId: 'm1', role: 'assistant' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'ghost', delta: 'salvaged' },
    ]
    const final = events.reduce(reduce, EMPTY_CHAT_SNAPSHOT)
    expect(final.messages[0]?.content).toBe('salvaged')
  })

  it('CONTENT with empty message list is a no-op', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'TEXT_MESSAGE_CONTENT',
      messageId: 'm1',
      delta: 'lost',
    })
    expect(s1.messages).toHaveLength(0)
  })

  it('MESSAGES_SNAPSHOT replaces wholesale', () => {
    const s0: ChatStateSnapshot = {
      ...EMPTY_CHAT_SNAPSHOT,
      messages: [{ id: 'old', role: 'user', content: 'old', isStreaming: true }],
    }
    const s1 = reduce(s0, {
      type: 'MESSAGES_SNAPSHOT',
      messages: [{ id: 'new', role: 'assistant', content: 'replaced' }],
    })
    expect(s1.messages).toHaveLength(1)
    expect(s1.messages[0]).toMatchObject({ id: 'new', role: 'assistant', content: 'replaced', isStreaming: false })
  })

  it('parses unknown roles defensively as assistant', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'TEXT_MESSAGE_START',
      messageId: 'm1',
      role: 'mystery',
    })
    expect(s1.messages[0]?.role).toBe('assistant')
  })
})

describe('reduce — agent state + JSON Patch', () => {
  it('STATE_SNAPSHOT replaces agentState', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'STATE_SNAPSHOT',
      snapshot: { model: 'gpt-5', files: ['a.py', 'b.py'] },
    })
    expect(s1.agentState.model).toBe('gpt-5')
    expect(s1.agentState.files).toEqual(['a.py', 'b.py'])
  })

  it('STATE_DELTA applies RFC 6902 patches', () => {
    const seeded = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'STATE_SNAPSHOT',
      snapshot: { model: 'gpt-5', files: [] },
    })
    const patched = reduce(seeded, {
      type: 'STATE_DELTA',
      delta: [
        { op: 'replace', path: '/model', value: 'gpt-5-pro' },
        { op: 'add', path: '/files/-', value: 'x.py' },
      ],
    })
    expect(patched.agentState.model).toBe('gpt-5-pro')
    expect(patched.agentState.files).toEqual(['x.py'])
  })

  it('malformed STATE_DELTA leaves the snapshot unchanged', () => {
    const seeded = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'STATE_SNAPSHOT',
      snapshot: { model: 'gpt-5' },
    })
    const broken = reduce(seeded, {
      type: 'STATE_DELTA',
      delta: [{ op: 'replace', path: '/missing/deep/path', value: 1 }],
    })
    expect(broken.agentState.model).toBe('gpt-5') // unchanged
    expect(broken).toBe(seeded) // identity preserved on failure
  })
})

describe('reduce — tool calls', () => {
  it('appends a running tool call on TOOL_CALL_START', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'TOOL_CALL_START',
      toolCallId: 't1',
      toolCallName: 'read_file',
    })
    expect(s1.activeToolCalls).toEqual([{ id: 't1', name: 'read_file', status: 'running' }])
  })

  it('TOOL_CALL_ARGS is intentionally a no-op (Pillar G.2 will revisit)', () => {
    const s0 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'TOOL_CALL_START',
      toolCallId: 't1',
      toolCallName: 'read_file',
    })
    const s1 = reduce(s0, { type: 'TOOL_CALL_ARGS', toolCallId: 't1', delta: '{"path"' })
    expect(s1).toBe(s0)
  })

  it('TOOL_CALL_END marks the call completed', () => {
    const s0 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'TOOL_CALL_START',
      toolCallId: 't1',
      toolCallName: 'read_file',
    })
    const s1 = reduce(s0, { type: 'TOOL_CALL_END', toolCallId: 't1' })
    expect(s1.activeToolCalls[0]?.status).toBe('completed')
  })
})

describe('reduce — custom + activity', () => {
  it('CUSTOM deepagent.user_prompt sets pendingPrompt', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'CUSTOM',
      name: 'deepagent.user_prompt',
      value: {
        toolCallId: 't1',
        question: 'Continue?',
        options: [
          { id: 'yes', label: 'Yes' },
          { id: 'no', label: 'No' },
        ],
      },
    })
    expect(s1.pendingPrompt).toMatchObject({
      toolCallId: 't1',
      question: 'Continue?',
    })
    expect(s1.pendingPrompt?.options).toHaveLength(2)
  })

  it('CUSTOM with unknown name is a silent no-op', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'CUSTOM',
      name: 'deepagent.future_feature',
      value: { anything: 'goes' },
    })
    expect(s1).toBe(EMPTY_CHAT_SNAPSHOT)
  })

  it('ACTIVITY_SNAPSHOT routes target=canvas to canvasActivity', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'ACTIVITY_SNAPSHOT',
      messageId: 'm1',
      activityType: 'render',
      content: { target: 'canvas', engine: 'ag-ui' },
    })
    expect(s1.canvasActivity).not.toBeNull()
    expect(s1.workspaceActivity).toBeNull()
  })

  it('ACTIVITY_SNAPSHOT routes default to workspaceActivity', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'ACTIVITY_SNAPSHOT',
      messageId: 'm1',
      activityType: 'render',
      content: {},
    })
    expect(s1.canvasActivity).toBeNull()
    expect(s1.workspaceActivity).not.toBeNull()
  })

  it('UNKNOWN events are no-ops', () => {
    const s1 = reduce(EMPTY_CHAT_SNAPSHOT, {
      type: 'UNKNOWN',
      rawType: 'FUTURE_EVENT',
      raw: { type: 'FUTURE_EVENT' },
    })
    expect(s1).toBe(EMPTY_CHAT_SNAPSHOT)
  })
})

describe('reduce — purity', () => {
  it('does not mutate input snapshot on any path', () => {
    const s0 = { ...EMPTY_CHAT_SNAPSHOT }
    const frozen = Object.freeze({ ...s0, messages: Object.freeze([...s0.messages]) })
    const events: AgUiEvent[] = [
      { type: 'RUN_STARTED' },
      { type: 'TEXT_MESSAGE_START', messageId: 'm1', role: 'assistant' },
      { type: 'TEXT_MESSAGE_CONTENT', messageId: 'm1', delta: 'x' },
      { type: 'TOOL_CALL_START', toolCallId: 't1', toolCallName: 'go' },
      { type: 'TOOL_CALL_END', toolCallId: 't1' },
      { type: 'RUN_FINISHED' },
    ]
    expect(() => events.reduce(reduce, frozen as ChatStateSnapshot)).not.toThrow()
  })
})

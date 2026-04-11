import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock crypto.randomUUID for deterministic IDs
let uuidCounter = 0
vi.stubGlobal('crypto', {
  randomUUID: () => `uuid-${++uuidCounter}`,
})

// Mock import.meta.env
vi.stubGlobal('import', { meta: { env: { VITE_AGENT_BASE_URL: 'http://test:8000' } } })

// Mock @ag-ui/client
const mockRunAgent = vi.fn()
vi.mock('@ag-ui/client', () => ({
  HttpAgent: vi.fn().mockImplementation(() => ({
    runAgent: mockRunAgent,
    setMessages: vi.fn(),
    setState: vi.fn(),
    headers: {},
  })),
}))

// Mock useAuth for Bearer token forwarding
vi.mock('@/shared/composables/useAuth', () => ({
  useAuth: () => ({
    getToken: () => Promise.resolve(null),
  }),
}))

import { useAgentClient } from './useAgentClient'

describe('useAgentClient', () => {
  beforeEach(() => {
    uuidCounter = 0
    vi.clearAllMocks()
    mockRunAgent.mockReset()

    // Reset module-level state by calling resetThread
    const { resetThread } = useAgentClient()
    resetThread()
    uuidCounter = 0
  })

  it('addUserMessage adds message with role user, string content, and id', () => {
    const { addUserMessage, messages } = useAgentClient()
    addUserMessage('Hello')

    const msg = messages.value[0]
    expect(msg.role).toBe('user')
    expect(msg.content).toBe('Hello')
    expect(msg.id).toBe('uuid-1')
  })

  it('addUserMessage increments messages.value length', () => {
    const { addUserMessage, messages } = useAgentClient()
    expect(messages.value).toHaveLength(0)

    addUserMessage('First')
    expect(messages.value).toHaveLength(1)

    addUserMessage('Second')
    expect(messages.value).toHaveLength(2)
  })

  it('runAgent calls HttpAgent.runAgent', async () => {
    mockRunAgent.mockResolvedValue(undefined)

    const { runAgent } = useAgentClient()
    await runAgent()

    expect(mockRunAgent).toHaveBeenCalledTimes(1)
  })

  it('runAgent sets isRunning to true', async () => {
    mockRunAgent.mockResolvedValue(undefined)

    const { runAgent, isRunning } = useAgentClient()
    const promise = runAgent()

    // isRunning is set before the await resolves
    await promise
    // After runAgent completes without onRunFinished, isRunning stays true
    // (only event handlers toggle it back)
    expect(isRunning.value).toBe(true)
  })

  it('onRunFinishedEvent sets isRunning to false', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onRunFinishedEvent({ event: {} })
    })

    const { runAgent, isRunning } = useAgentClient()
    await runAgent()

    expect(isRunning.value).toBe(false)
  })

  it('onRunErrorEvent sets error and isRunning to false', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onRunErrorEvent({ event: { message: 'Something broke' } })
    })

    const { runAgent, error, isRunning } = useAgentClient()
    await runAgent()

    expect(error.value).toBeInstanceOf(Error)
    expect(error.value!.message).toBe('Something broke')
    expect(isRunning.value).toBe(false)
  })

  it('onTextMessageStartEvent adds new message', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onTextMessageStartEvent({
        event: { messageId: 'msg-1', role: 'assistant' },
      })
    })

    const { runAgent, messages } = useAgentClient()
    await runAgent()

    expect(messages.value).toHaveLength(1)
    expect(messages.value[0].id).toBe('msg-1')
    expect(messages.value[0].role).toBe('assistant')
    expect(messages.value[0].content).toBe('')
  })

  it('onTextMessageContentEvent appends to last message content', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onTextMessageStartEvent({
        event: { messageId: 'msg-1', role: 'assistant' },
      })
      await subscriber.onTextMessageContentEvent({
        event: { delta: 'Hello ' },
      })
      await subscriber.onTextMessageContentEvent({
        event: { delta: 'world' },
      })
    })

    const { runAgent, messages } = useAgentClient()
    await runAgent()

    expect(messages.value[0].content).toBe('Hello world')
  })

  it('onStateSnapshotEvent updates state', async () => {
    const snapshot = { todos: [{ content: 'Test', status: 'done' }] }
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onStateSnapshotEvent({ event: { snapshot } })
    })

    const { runAgent, state } = useAgentClient()
    await runAgent()

    expect(state.value).toEqual(snapshot)
  })

  it('onCustomEvent with deepagent.state_snapshot updates customState', async () => {
    const payload = { cost: { total_usd: 0.05, total_tokens: 100, run_usd: 0.01, run_tokens: 50 } }
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onCustomEvent({
        event: { name: 'deepagent.state_snapshot', value: payload },
      })
    })

    const { runAgent, customState } = useAgentClient()
    await runAgent()

    expect(customState.value).toEqual(payload)
  })

  it('resetThread clears messages, state, customState, error', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onTextMessageStartEvent({
        event: { messageId: 'msg-1', role: 'assistant' },
      })
      await subscriber.onStateSnapshotEvent({ event: { snapshot: { files: ['a.txt'] } } })
      await subscriber.onCustomEvent({
        event: { name: 'deepagent.state_snapshot', value: { cost: {} } },
      })
    })

    const { runAgent, resetThread, messages, state, customState, error } = useAgentClient()
    await runAgent()

    expect(messages.value).toHaveLength(1)

    resetThread()

    expect(messages.value).toEqual([])
    expect(state.value).toEqual({})
    expect(customState.value).toEqual({})
    expect(error.value).toBeNull()
  })

  it('resetThread generates new threadId (messages.value is empty array after reset)', () => {
    const { addUserMessage, resetThread, messages } = useAgentClient()
    addUserMessage('Hello')
    expect(messages.value).toHaveLength(1)

    resetThread()

    expect(messages.value).toHaveLength(0)
    expect(messages.value).toEqual([])
  })

  it('runAgent with thrown error sets error.value', async () => {
    mockRunAgent.mockRejectedValue(new Error('Network failure'))

    const { runAgent, error, isRunning } = useAgentClient()
    await runAgent()

    expect(error.value).toBeInstanceOf(Error)
    expect(error.value!.message).toBe('Network failure')
    expect(isRunning.value).toBe(false)
  })

  it('runAgent with non-Error thrown value wraps it in Error', async () => {
    mockRunAgent.mockRejectedValue('string error')

    const { runAgent, error } = useAgentClient()
    await runAgent()

    expect(error.value).toBeInstanceOf(Error)
    expect(error.value!.message).toBe('string error')
  })

  it('runAgent clears previous error before starting', async () => {
    mockRunAgent.mockRejectedValueOnce(new Error('First failure'))

    const { runAgent, error } = useAgentClient()
    await runAgent()
    expect(error.value).not.toBeNull()

    mockRunAgent.mockResolvedValueOnce(undefined)
    await runAgent()
    expect(error.value).toBeNull()
  })

  it('runAgent passes forwardedProps with model and approval', async () => {
    mockRunAgent.mockResolvedValueOnce(undefined)
    const { addUserMessage, runAgent } = useAgentClient()
    addUserMessage('Hello')
    await runAgent({ model: 'openai:gpt-4.1-mini', approval: 'bypass' })
    const callArgs = mockRunAgent.mock.calls[0][0]
    expect(callArgs.forwardedProps).toEqual({ model: 'openai:gpt-4.1-mini', approval: 'bypass' })
  })

  it('runAgent sends empty forwardedProps when no options', async () => {
    mockRunAgent.mockResolvedValueOnce(undefined)
    const { addUserMessage, runAgent } = useAgentClient()
    addUserMessage('Hello')
    await runAgent()
    const callArgs = mockRunAgent.mock.calls[0][0]
    expect(callArgs.forwardedProps).toEqual({})
  })

  // ── AG-UI standard state events ──

  it('onStateSnapshotEvent (standard AG-UI) updates customState', async () => {
    const snapshot = { cost: { total_usd: 0.10 }, model: 'test' }
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onStateSnapshotEvent({ event: { snapshot } })
    })

    const { runAgent, customState } = useAgentClient()
    await runAgent()

    expect(customState.value).toEqual(snapshot)
  })

  it('onStateDeltaEvent patches customState', async () => {
    // First set initial state
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onStateSnapshotEvent({
        event: { snapshot: { model: 'gpt-4', count: 1 } },
      })
      await subscriber.onStateDeltaEvent({
        event: { delta: [{ op: 'replace', path: '/count', value: 42 }] },
      })
    })

    const { runAgent, customState } = useAgentClient()
    await runAgent()

    expect(customState.value.count).toBe(42)
    expect(customState.value.model).toBe('gpt-4')
  })

  // ── Activity events ──

  it('onActivitySnapshotEvent routes workspace activity', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onActivitySnapshotEvent({
        event: {
          activityType: 'approval_review',
          messageId: 'msg-act-1',
          content: { engine: 'ag-ui', target: 'workspace', component_name: 'approval_review' },
        },
      })
    })

    const { runAgent, workspaceActivity } = useAgentClient()
    await runAgent()

    expect(workspaceActivity.value).not.toBeNull()
    expect(workspaceActivity.value!.activityType).toBe('approval_review')
    expect(workspaceActivity.value!.content.target).toBe('workspace')
  })

  it('onActivitySnapshotEvent routes canvas activity', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onActivitySnapshotEvent({
        event: {
          activityType: 'chart_view',
          messageId: 'msg-act-2',
          content: { engine: 'ag-ui', target: 'canvas', component_name: 'chart_view' },
        },
      })
    })

    const { runAgent, canvasActivity } = useAgentClient()
    await runAgent()

    expect(canvasActivity.value).not.toBeNull()
    expect(canvasActivity.value!.activityType).toBe('chart_view')
    expect(canvasActivity.value!.content.target).toBe('canvas')
  })

  // ── Tool call tracking ──

  it('onToolCallStartEvent adds to activeToolCalls', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-1', toolCallName: 'execute' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value).toHaveLength(1)
    expect(activeToolCalls.value[0]).toEqual({ id: 'tc-1', name: 'execute', status: 'running' })
  })

  it('onToolCallEndEvent marks tool call completed', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-2', toolCallName: 'read_file' },
      })
      await subscriber.onToolCallEndEvent({
        event: { toolCallId: 'tc-2' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value[0].status).toBe('completed')
  })

  // ── HITL respondToPrompt ──

  it('respondToPrompt sends hitl_response in forwardedProps', async () => {
    // First simulate a pending prompt
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onCustomEvent({
        event: {
          name: 'deepagent.user_prompt',
          value: { tool_call_id: 'call-ask-1', question: 'Choose?', options: [{ label: 'A' }] },
        },
      })
    })

    const { runAgent, respondToPrompt, pendingPrompt } = useAgentClient()
    await runAgent()

    expect(pendingPrompt.value).not.toBeNull()

    // Now respond — this triggers a new runAgent call
    mockRunAgent.mockResolvedValueOnce(undefined)
    respondToPrompt('A')

    expect(pendingPrompt.value).toBeNull()

    // Wait for the async runAgent inside respondToPrompt
    await new Promise((r) => setTimeout(r, 10))

    // The second call should have hitl_response in forwardedProps
    const lastCall = mockRunAgent.mock.calls[mockRunAgent.mock.calls.length - 1]
    expect(lastCall[0].forwardedProps.hitl_response).toEqual({
      tool_call_id: 'call-ask-1',
      answer: 'A',
    })
  })

  // ── Reset clears new state ──

  it('resetThread clears canvas, workspace, and toolCalls', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onActivitySnapshotEvent({
        event: {
          activityType: 'chart',
          messageId: 'msg-1',
          content: { engine: 'ag-ui', target: 'canvas' },
        },
      })
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-1', toolCallName: 'execute' },
      })
    })

    const { runAgent, resetThread, canvasActivity, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(canvasActivity.value).not.toBeNull()
    expect(activeToolCalls.value).toHaveLength(1)

    resetThread()

    expect(canvasActivity.value).toBeNull()
    expect(activeToolCalls.value).toEqual([])
  })
})

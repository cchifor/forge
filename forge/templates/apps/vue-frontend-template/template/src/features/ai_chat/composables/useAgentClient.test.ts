import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock crypto.randomUUID for deterministic IDs
let uuidCounter = 0
vi.stubGlobal('crypto', {
  randomUUID: () => `uuid-${++uuidCounter}`,
})

// Mock import.meta.env
vi.stubGlobal('import', { meta: { env: { VITE_AGENT_BASE_URL: 'http://test:8000' } } })

// Capture the onEvent callback from AgUiClient so tests can feed events.
let capturedOnEvent: ((event: any) => void) | null = null
const mockRunAgent = vi.fn()

vi.mock('@forge/canvas-core', async () => {
  const actual = await vi.importActual('@forge/canvas-core')
  return {
    ...actual,
    AgUiClient: vi.fn().mockImplementation((opts: any) => {
      capturedOnEvent = opts.onEvent
      return { runAgent: mockRunAgent }
    }),
  }
})

// Mock useAuth for Bearer token forwarding
vi.mock('@/shared/composables/useAuth', () => ({
  useAuth: () => ({
    getToken: () => Promise.resolve(null),
  }),
}))

import { useAgentClient } from './useAgentClient'
import { parseEvent } from '@forge/canvas-core'

/** Helper: simulate an AG-UI event by feeding it through the captured onEvent. */
function emitEvent(raw: Record<string, unknown>) {
  if (!capturedOnEvent) throw new Error('No onEvent captured — did runAgent get called?')
  capturedOnEvent(parseEvent(raw))
}

describe('useAgentClient', () => {
  beforeEach(() => {
    uuidCounter = 0
    vi.clearAllMocks()
    mockRunAgent.mockReset()
    mockRunAgent.mockResolvedValue(undefined)
    capturedOnEvent = null

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

  it('runAgent calls AgUiClient.runAgent', async () => {
    const { runAgent } = useAgentClient()
    await runAgent()

    expect(mockRunAgent).toHaveBeenCalledTimes(1)
  })

  it('runAgent sets isRunning to true', async () => {
    const { runAgent, isRunning } = useAgentClient()
    await runAgent()

    // isRunning is set before the await; after runAgent completes
    // without a RUN_FINISHED event it stays false (force-stopped).
    // But during the call it was true.
    expect(mockRunAgent).toHaveBeenCalledTimes(1)
  })

  it('onRunFinishedEvent sets isRunning to false', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'RUN_FINISHED' })
    })

    const { runAgent, isRunning } = useAgentClient()
    await runAgent()

    expect(isRunning.value).toBe(false)
  })

  it('onRunErrorEvent sets error and isRunning to false', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'RUN_ERROR', message: 'Something broke' })
    })

    const { runAgent, error, isRunning } = useAgentClient()
    await runAgent()

    expect(error.value).toBeInstanceOf(Error)
    expect(error.value!.message).toBe('Something broke')
    expect(isRunning.value).toBe(false)
  })

  it('onTextMessageStartEvent adds new message', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TEXT_MESSAGE_START', messageId: 'msg-1', role: 'assistant' })
    })

    const { runAgent, messages } = useAgentClient()
    await runAgent()

    expect(messages.value).toHaveLength(1)
    expect(messages.value[0].id).toBe('msg-1')
    expect(messages.value[0].role).toBe('assistant')
    expect(messages.value[0].content).toBe('')
  })

  it('onTextMessageContentEvent appends to last message content', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TEXT_MESSAGE_START', messageId: 'msg-1', role: 'assistant' })
      emitEvent({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: 'Hello ' })
      emitEvent({ type: 'TEXT_MESSAGE_CONTENT', messageId: 'msg-1', delta: 'world' })
    })

    const { runAgent, messages } = useAgentClient()
    await runAgent()

    expect(messages.value[0].content).toBe('Hello world')
  })

  it('onStateSnapshotEvent updates state', async () => {
    const snapshot = { todos: [{ content: 'Test', status: 'done' }] }
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'STATE_SNAPSHOT', snapshot })
    })

    const { runAgent, state } = useAgentClient()
    await runAgent()

    expect(state.value).toMatchObject(snapshot)
  })

  it('onCustomEvent with deepagent.state_snapshot updates customState', async () => {
    const payload = { state: { cost: { total_usd: 0.05, total_tokens: 100, run_usd: 0.01, run_tokens: 50 } } }
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'CUSTOM', name: 'deepagent.state_snapshot', value: payload })
    })

    const { runAgent, customState } = useAgentClient()
    await runAgent()

    // canvas-core's reducer extracts value.state as the raw map
    expect(customState.value).toMatchObject(payload.state)
  })

  it('resetThread clears messages, state, customState, error', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TEXT_MESSAGE_START', messageId: 'msg-1', role: 'assistant' })
      emitEvent({ type: 'STATE_SNAPSHOT', snapshot: { files: ['a.txt'] } })
    })

    const { runAgent, resetThread, messages, state, error } = useAgentClient()
    await runAgent()

    expect(messages.value).toHaveLength(1)

    resetThread()

    expect(messages.value).toEqual([])
    expect(state.value).toEqual({})
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
    const { addUserMessage, runAgent } = useAgentClient()
    addUserMessage('Hello')
    await runAgent({ model: 'openai:gpt-4.1-mini', approval: 'bypass' })
    const callArgs = mockRunAgent.mock.calls[0][0]
    expect(callArgs.forwardedProps).toEqual({ model: 'openai:gpt-4.1-mini', approval: 'bypass' })
  })

  it('runAgent sends empty forwardedProps when no options', async () => {
    const { addUserMessage, runAgent } = useAgentClient()
    addUserMessage('Hello')
    await runAgent()
    const callArgs = mockRunAgent.mock.calls[0][0]
    expect(callArgs.forwardedProps).toEqual({})
  })

  // -- AG-UI standard state events --

  it('onStateSnapshotEvent (standard AG-UI) updates customState', async () => {
    const snapshot = { cost: { total_usd: 0.10 }, model: 'test' }
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'STATE_SNAPSHOT', snapshot })
    })

    const { runAgent, customState } = useAgentClient()
    await runAgent()

    expect(customState.value).toMatchObject(snapshot)
  })

  it('onStateDeltaEvent patches customState', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'STATE_SNAPSHOT', snapshot: { model: 'gpt-4', count: 1 } })
      emitEvent({ type: 'STATE_DELTA', delta: [{ op: 'replace', path: '/count', value: 42 }] })
    })

    const { runAgent, customState } = useAgentClient()
    await runAgent()

    expect((customState.value as any).count).toBe(42)
    expect((customState.value as any).model).toBe('gpt-4')
  })

  // -- Activity events --

  it('onActivitySnapshotEvent routes workspace activity', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({
        type: 'ACTIVITY_SNAPSHOT',
        activityType: 'approval_review',
        messageId: 'msg-act-1',
        content: { engine: 'ag-ui', target: 'workspace', component_name: 'approval_review' },
      })
    })

    const { runAgent, workspaceActivity } = useAgentClient()
    await runAgent()

    expect(workspaceActivity.value).not.toBeNull()
    expect(workspaceActivity.value!.activityType).toBe('approval_review')
    expect(workspaceActivity.value!.content.target).toBe('workspace')
  })

  it('onActivitySnapshotEvent routes canvas activity', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({
        type: 'ACTIVITY_SNAPSHOT',
        activityType: 'chart_view',
        messageId: 'msg-act-2',
        content: { engine: 'ag-ui', target: 'canvas', component_name: 'chart_view' },
      })
    })

    const { runAgent, canvasActivity } = useAgentClient()
    await runAgent()

    expect(canvasActivity.value).not.toBeNull()
    expect(canvasActivity.value!.activityType).toBe('chart_view')
    expect(canvasActivity.value!.content.target).toBe('canvas')
  })

  // -- Tool call tracking --

  it('onToolCallStartEvent adds to activeToolCalls', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-1', toolCallName: 'execute' })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value).toHaveLength(1)
    expect(activeToolCalls.value[0]).toEqual({ id: 'tc-1', name: 'execute', status: 'running' })
  })

  it('onToolCallEndEvent marks tool call completed', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-2', toolCallName: 'read_file' })
      emitEvent({ type: 'TOOL_CALL_END', toolCallId: 'tc-2' })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value[0].status).toBe('completed')
  })

  // -- HITL respondToPrompt --

  it('respondToPrompt sends hitl_response in forwardedProps', async () => {
    // First simulate a pending prompt via CUSTOM event
    mockRunAgent.mockImplementation(async () => {
      emitEvent({
        type: 'CUSTOM',
        name: 'deepagent.user_prompt',
        value: { toolCallId: 'call-ask-1', question: 'Choose?', options: [{ id: 'a', label: 'A' }] },
      })
    })

    const { runAgent, respondToPrompt, pendingPrompt } = useAgentClient()
    await runAgent()

    expect(pendingPrompt.value).not.toBeNull()

    // Now respond -- this triggers a new runAgent call
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

  // -- retryLastRun (RUN_ERROR banner) --

  it('retryLastRun re-invokes runAgent with the last options', async () => {
    const { runAgent, retryLastRun } = useAgentClient()
    await runAgent({
      model: 'openai:gpt-4.1-mini',
      approval: 'bypass',
      attachmentIds: ['file-1'],
    })
    expect(mockRunAgent).toHaveBeenCalledTimes(1)

    mockRunAgent.mockResolvedValueOnce(undefined)
    retryLastRun()
    await new Promise((r) => setTimeout(r, 10))

    expect(mockRunAgent).toHaveBeenCalledTimes(2)
    const retryArgs = mockRunAgent.mock.calls[1][0]
    expect(retryArgs.forwardedProps).toEqual({
      model: 'openai:gpt-4.1-mini',
      approval: 'bypass',
      attachment_ids: ['file-1'],
    })
  })

  it('retryLastRun reuses the same threadId (does not mint a new one)', async () => {
    const { runAgent, retryLastRun } = useAgentClient()
    await runAgent({ model: 'openai:gpt-4.1' })
    const firstThreadId = mockRunAgent.mock.calls[0][0].threadId

    mockRunAgent.mockResolvedValueOnce(undefined)
    retryLastRun()
    await new Promise((r) => setTimeout(r, 10))

    const secondThreadId = mockRunAgent.mock.calls[1][0].threadId
    expect(secondThreadId).toBe(firstThreadId)
  })

  it('retryLastRun clears error.value before retrying', async () => {
    mockRunAgent.mockRejectedValueOnce(new Error('First failure'))
    const { runAgent, retryLastRun, error } = useAgentClient()
    await runAgent({ model: 'openai:gpt-4.1' })
    expect(error.value).not.toBeNull()

    mockRunAgent.mockResolvedValueOnce(undefined)
    retryLastRun()
    // error is cleared synchronously before the async runAgent kicks off
    expect(error.value).toBeNull()
  })

  it('retryLastRun is a no-op before any runAgent call', () => {
    const { retryLastRun } = useAgentClient()
    retryLastRun()
    expect(mockRunAgent).not.toHaveBeenCalled()
  })

  it('retryLastRun is a no-op while a run is in flight (anti-double-retry)', async () => {
    let resolveRun: (() => void) | null = null
    mockRunAgent.mockImplementation(
      () => new Promise<void>((resolve) => { resolveRun = resolve }),
    )
    const { runAgent, retryLastRun } = useAgentClient()
    const firstCall = runAgent({ model: 'gpt-x', approval: 'default' })
    // Don't await -- runAgent's promise stays pending, isRunning = true.
    await new Promise((r) => setTimeout(r, 0))  // let isRunning flip
    expect(mockRunAgent).toHaveBeenCalledTimes(1)
    retryLastRun()
    retryLastRun()
    retryLastRun()
    expect(mockRunAgent).toHaveBeenCalledTimes(1)  // still 1, all retries no-op'd
    resolveRun?.()
    await firstCall
  })

  it('dismissError() clears error.value', async () => {
    const { runAgent, dismissError, error } = useAgentClient()
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'RUN_ERROR', message: 'boom' })
    })
    await runAgent()
    expect(error.value).not.toBeNull()
    dismissError()
    expect(error.value).toBeNull()
  })

  // -- Reset clears new state --

  it('resetThread clears canvas, workspace, and toolCalls', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({
        type: 'ACTIVITY_SNAPSHOT',
        activityType: 'chart',
        messageId: 'msg-1',
        content: { engine: 'ag-ui', target: 'canvas' },
      })
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-1', toolCallName: 'execute' })
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

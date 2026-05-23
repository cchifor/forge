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

  // ── TOOL_CALL_ARGS streaming (Pillar G.2) ──

  it('onToolCallArgsEvent accumulates delta into argsBuffer', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-a', toolCallName: 'search' },
      })
      await subscriber.onToolCallArgsEvent({
        event: { toolCallId: 'tc-a', delta: '{"q":' },
      })
      await subscriber.onToolCallArgsEvent({
        event: { toolCallId: 'tc-a', delta: '"hi"}' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value[0].argsBuffer).toBe('{"q":"hi"}')
    // argsPretty is not set until TOOL_CALL_END.
    expect(activeToolCalls.value[0].argsPretty).toBeUndefined()
  })

  it('onToolCallEndEvent pretty-prints argsBuffer via JSON.stringify', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-b', toolCallName: 'search' },
      })
      await subscriber.onToolCallArgsEvent({
        event: { toolCallId: 'tc-b', delta: '{"q":"hi","n":1}' },
      })
      await subscriber.onToolCallEndEvent({
        event: { toolCallId: 'tc-b' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value[0].argsPretty).toBe(
      '{\n  "q": "hi",\n  "n": 1\n}',
    )
    expect(activeToolCalls.value[0].status).toBe('completed')
  })

  it('onToolCallEndEvent falls back to raw buffer on JSON parse error', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-c', toolCallName: 'search' },
      })
      await subscriber.onToolCallArgsEvent({
        event: { toolCallId: 'tc-c', delta: 'not-json{' },
      })
      await subscriber.onToolCallEndEvent({
        event: { toolCallId: 'tc-c' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    // Parse fails → argsPretty mirrors the raw delta so the user still
    // sees *something* in the collapsible preview.
    // Use a single open-brace; a doubled open-brace would collide
    // with Copier's Jinja print delimiters at template-render time.
    expect(activeToolCalls.value[0].argsPretty).toBe('not-json{')
  })

  it('concurrent tool calls keep separate argsBuffers (no cross-contamination)', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-x', toolCallName: 'a' },
      })
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-y', toolCallName: 'b' },
      })
      await subscriber.onToolCallArgsEvent({
        event: { toolCallId: 'tc-x', delta: '{"x":1}' },
      })
      await subscriber.onToolCallArgsEvent({
        event: { toolCallId: 'tc-y', delta: '{"y":2}' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    expect(activeToolCalls.value).toHaveLength(2)
    const x = activeToolCalls.value.find((t) => t.id === 'tc-x')
    const y = activeToolCalls.value.find((t) => t.id === 'tc-y')
    expect(x?.argsBuffer).toBe('{"x":1}')
    expect(y?.argsBuffer).toBe('{"y":2}')
  })

  it('onToolCallEndEvent with no args leaves argsPretty unset', async () => {
    mockRunAgent.mockImplementation(async (_params: any, subscriber: any) => {
      await subscriber.onToolCallStartEvent({
        event: { toolCallId: 'tc-empty', toolCallName: 'ping' },
      })
      await subscriber.onToolCallEndEvent({
        event: { toolCallId: 'tc-empty' },
      })
    })

    const { runAgent, activeToolCalls } = useAgentClient()
    await runAgent()

    // No TOOL_CALL_ARGS arrived — we don't fabricate an empty preview;
    // the collapsible just hides in the UI.
    expect(activeToolCalls.value[0].argsPretty).toBeUndefined()
    expect(activeToolCalls.value[0].argsBuffer).toBeUndefined()
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

  // ── retryLastRun (RUN_ERROR banner) ──

  it('retryLastRun re-invokes runAgent with the last options', async () => {
    mockRunAgent.mockResolvedValue(undefined)
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
    mockRunAgent.mockResolvedValue(undefined)
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
    // Codex Phase B round 1 follow-up. Spamming the Retry button
    // during a slow retry must not queue multiple runAgent calls.
    let resolveRun: (() => void) | null = null
    mockRunAgent.mockImplementation(
      () => new Promise<void>((resolve) => { resolveRun = resolve }),
    )
    const { runAgent, retryLastRun } = useAgentClient()
    const firstCall = runAgent({ model: 'gpt-x', approval: 'default' })
    // Don't await — runAgent's promise stays pending, isRunning = true.
    await new Promise((r) => setTimeout(r, 0))  // let isRunning flip
    expect(mockRunAgent).toHaveBeenCalledTimes(1)
    retryLastRun()
    retryLastRun()
    retryLastRun()
    expect(mockRunAgent).toHaveBeenCalledTimes(1)  // still 1, all retries no-op'd
    resolveRun?.()
    await firstCall
  })

  it('dismissError() clears error.value (public API, mirrors Svelte/Flutter)', async () => {
    // Codex Phase B round 1 follow-up: cross-stack consistency. Vue
    // exposes dismissError() now instead of forcing the UI layer to
    // mutate error.value directly.
    const { runAgent, dismissError, error } = useAgentClient()
    mockRunAgent.mockImplementation(async (_p: any, subscriber: any) => {
      await subscriber.onRunErrorEvent({ event: { message: 'boom' } })
    })
    await runAgent()
    expect(error.value).not.toBeNull()
    dismissError()
    expect(error.value).toBeNull()
  })

  // ── regenerate (G.3) ──

  // Helper: drive an assistant reply through the AG-UI event subscriber
  // so we get a real assistant message in `messages` without mutating
  // the readonly export. Returns once the first run resolves.
  async function seedAssistantReply(
    runAgentFn: (opts?: any) => Promise<void>,
    runOpts: any,
    asstId: string,
    asstContent: string,
  ) {
    mockRunAgent.mockImplementationOnce(async (_params: any, sub: any) => {
      await sub.onTextMessageStartEvent({
        event: { messageId: asstId, role: 'assistant' },
      })
      await sub.onTextMessageContentEvent({ event: { delta: asstContent } })
      await sub.onRunFinishedEvent({ event: {} })
    })
    await runAgentFn(runOpts)
  }

  it('regenerate truncates from messageId onward and re-runs', async () => {
    const { addUserMessage, runAgent, regenerate, messages } = useAgentClient()
    addUserMessage('hi')
    await seedAssistantReply(runAgent, { model: 'openai:gpt-4.1' }, 'asst-1', 'previous reply')
    expect(messages.value).toHaveLength(2)
    expect(messages.value[1].id).toBe('asst-1')

    mockRunAgent.mockResolvedValueOnce(undefined)
    regenerate('asst-1')
    await new Promise((r) => setTimeout(r, 10))

    // The assistant message we regenerated FROM is dropped — runAgent
    // is invoked again so the agent can stream a fresh reply.
    expect(messages.value).toHaveLength(1)
    expect(messages.value[0].role).toBe('user')
    expect(mockRunAgent).toHaveBeenCalledTimes(2)
  })

  it('regenerate preserves currentThreadId (does NOT mint a new thread)', async () => {
    const { addUserMessage, runAgent, regenerate } = useAgentClient()
    addUserMessage('hi')
    await seedAssistantReply(runAgent, { model: 'openai:gpt-4.1' }, 'asst-2', 'reply')
    const firstThreadId = mockRunAgent.mock.calls[0][0].threadId

    mockRunAgent.mockResolvedValueOnce(undefined)
    regenerate('asst-2')
    await new Promise((r) => setTimeout(r, 10))

    const regenThreadId = mockRunAgent.mock.calls[1][0].threadId
    // ── Load-bearing invariant: regenerate keeps the thread. ──
    expect(regenThreadId).toBe(firstThreadId)
  })

  it('regenerate re-uses lastRunOptions (model + approval + attachments)', async () => {
    const { addUserMessage, runAgent, regenerate } = useAgentClient()
    addUserMessage('hi')
    await seedAssistantReply(
      runAgent,
      {
        model: 'anthropic:claude-sonnet-4-20250514',
        approval: 'bypass',
        attachmentIds: ['file-7'],
      },
      'asst-3',
      'reply',
    )

    mockRunAgent.mockResolvedValueOnce(undefined)
    regenerate('asst-3')
    await new Promise((r) => setTimeout(r, 10))

    const regenArgs = mockRunAgent.mock.calls[1][0]
    expect(regenArgs.forwardedProps).toEqual({
      model: 'anthropic:claude-sonnet-4-20250514',
      approval: 'bypass',
      attachment_ids: ['file-7'],
    })
  })

  it('regenerate is a no-op for unknown messageId', async () => {
    mockRunAgent.mockResolvedValue(undefined)
    const { addUserMessage, runAgent, regenerate, messages } = useAgentClient()
    addUserMessage('hi')
    await runAgent()
    expect(mockRunAgent).toHaveBeenCalledTimes(1)

    regenerate('does-not-exist')
    await new Promise((r) => setTimeout(r, 10))

    expect(messages.value).toHaveLength(1)
    expect(mockRunAgent).toHaveBeenCalledTimes(1)
  })

  it('regenerate is a no-op while a run is in flight (anti-double-click)', async () => {
    // First produce a successful turn so we have an assistant message
    // to point regenerate at.
    const { addUserMessage, runAgent, regenerate, messages } = useAgentClient()
    addUserMessage('hi')
    await seedAssistantReply(runAgent, { model: 'gpt-x' }, 'asst-x', 'first reply')
    expect(messages.value).toHaveLength(2)

    // Now start a second run that never resolves — leaves isRunning=true.
    let resolveRun: (() => void) | null = null
    mockRunAgent.mockImplementationOnce(
      () => new Promise<void>((resolve) => { resolveRun = resolve }),
    )
    const inflight = runAgent({ model: 'gpt-x' })
    await new Promise((r) => setTimeout(r, 0))
    expect(mockRunAgent).toHaveBeenCalledTimes(2)

    regenerate('asst-x')
    regenerate('asst-x')
    regenerate('asst-x')

    // Still 2 — all three regen calls no-op'd because isRunning=true.
    expect(mockRunAgent).toHaveBeenCalledTimes(2)
    // And messages weren't truncated either — guard fires BEFORE slice.
    expect(messages.value).toHaveLength(2)

    resolveRun?.()
    await inflight
  })

  it('regenerate is a no-op when no prior runAgent has fired (hasRun gate)', () => {
    // Codex Phase B round 1 follow-up. Calling regenerate before any
    // runAgent has captured `lastRunOptions` would otherwise fall
    // through to runAgent(undefined), silently re-running with empty
    // forwardedProps. The hasRun gate prevents this.
    const { regenerate, addUserMessage } = useAgentClient()
    // Seed a message but DON'T fire runAgent (which is what would
    // happen if a user typed but clicked Regenerate on stale state).
    addUserMessage('hi')
    regenerate('user-msg-id-that-may-or-may-not-exist')
    // Even if the id matched, regenerate must short-circuit on the
    // hasRun gate BEFORE truncating + calling runAgent.
    expect(mockRunAgent).not.toHaveBeenCalled()
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

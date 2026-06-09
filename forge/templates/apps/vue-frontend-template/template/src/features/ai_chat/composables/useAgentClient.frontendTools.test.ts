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
import { FRONTEND_TOOLS } from '../tools/frontendTools'

/** Helper: simulate an AG-UI event by feeding it through the captured onEvent. */
function emitEvent(raw: Record<string, unknown>) {
  if (!capturedOnEvent) throw new Error('No onEvent captured — did runAgent get called?')
  capturedOnEvent(parseEvent(raw))
}

describe('useAgentClient — frontend tools', () => {
  beforeEach(() => {
    uuidCounter = 0
    vi.clearAllMocks()
    mockRunAgent.mockReset()
    mockRunAgent.mockResolvedValue(undefined)
    capturedOnEvent = null

    const { resetThread } = useAgentClient()
    resetThread()
    uuidCounter = 0
  })

  it('runAgent sends FRONTEND_TOOLS in the payload tools field', async () => {
    const { runAgent } = useAgentClient()
    await runAgent()

    const callArgs = mockRunAgent.mock.calls[0][0]
    expect(callArgs.tools).toBe(FRONTEND_TOOLS)
    expect(callArgs.tools.map((t: any) => t.name)).toContain('show_dynamic_form')
  })

  it('TOOL_CALL_START/ARGS/END for show_dynamic_form synthesizes a dynamic_form canvasActivity with _toolCallId', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-form-1', toolCallName: 'show_dynamic_form' })
      emitEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 'tc-form-1', delta: '{"title":"Sign up",' })
      emitEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 'tc-form-1', delta: '"fields":[]}' })
      emitEvent({ type: 'TOOL_CALL_END', toolCallId: 'tc-form-1' })
    })

    const { runAgent, canvasActivity } = useAgentClient()
    await runAgent()

    const activity = canvasActivity.value
    expect(activity).not.toBeNull()
    expect(activity!.engine).toBe('ag-ui')
    expect(activity!.activityType).toBe('dynamic_form')
    expect(activity!.messageId).toBe('tc-form-1')
    // Contract: parsed args under content.props, toolCallId under content._toolCallId.
    expect(activity!.content.props).toEqual({ title: 'Sign up', fields: [] })
    expect(activity!.content._toolCallId).toBe('tc-form-1')
  })

  it('a non-frontend tool call does not open a canvas activity', async () => {
    mockRunAgent.mockImplementation(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-x', toolCallName: 'read_file' })
      emitEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 'tc-x', delta: '{"path":"a"}' })
      emitEvent({ type: 'TOOL_CALL_END', toolCallId: 'tc-x' })
    })

    const { runAgent, canvasActivity } = useAgentClient()
    await runAgent()

    expect(canvasActivity.value).toBeNull()
  })

  it('respondToFrontendTool appends a role:tool message with the toolCallId and resumes', async () => {
    // First: drive a deferred frontend-tool call so the assistant toolCalls
    // record gets recorded for resume.
    mockRunAgent.mockImplementationOnce(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-form-9', toolCallName: 'show_dynamic_form' })
      emitEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 'tc-form-9', delta: '{"title":"T","fields":[]}' })
      emitEvent({ type: 'TOOL_CALL_END', toolCallId: 'tc-form-9' })
    })

    const { runAgent, respondToFrontendTool, canvasActivity } = useAgentClient()
    await runAgent()
    expect(canvasActivity.value).not.toBeNull()

    // Now resolve the tool — this triggers a resume runAgent.
    mockRunAgent.mockResolvedValueOnce(undefined)
    respondToFrontendTool('tc-form-9', JSON.stringify({ name: 'Ada' }))
    await new Promise((r) => setTimeout(r, 10))

    // Canvas closed on resolve.
    expect(canvasActivity.value).toBeNull()

    // The resume payload must carry both the assistant toolCalls record AND
    // the role:'tool' result keyed by the same toolCallId.
    const resumeCall = mockRunAgent.mock.calls[mockRunAgent.mock.calls.length - 1][0]
    const msgs = resumeCall.messages as Array<Record<string, any>>

    const assistantToolCall = msgs.find(
      (m) => m.role === 'assistant' && Array.isArray(m.toolCalls),
    )
    expect(assistantToolCall).toBeDefined()
    expect(assistantToolCall!.toolCalls[0].id).toBe('tc-form-9')
    expect(assistantToolCall!.toolCalls[0].function.name).toBe('show_dynamic_form')

    const toolResult = msgs.find((m) => m.role === 'tool')
    expect(toolResult).toBeDefined()
    expect(toolResult!.toolCallId).toBe('tc-form-9')
    expect(toolResult!.content).toBe(JSON.stringify({ name: 'Ada' }))
  })

  it('outgoing messages mapping carries toolCallId/toolCalls for resume', async () => {
    mockRunAgent.mockImplementationOnce(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-a', toolCallName: 'show_approval' })
      emitEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 'tc-a', delta: '{"title":"Ok?","message":"Proceed"}' })
      emitEvent({ type: 'TOOL_CALL_END', toolCallId: 'tc-a' })
    })

    const { runAgent, respondToFrontendTool } = useAgentClient()
    await runAgent()

    mockRunAgent.mockResolvedValueOnce(undefined)
    respondToFrontendTool('tc-a', JSON.stringify({ approved: true }))
    await new Promise((r) => setTimeout(r, 10))

    const resumeCall = mockRunAgent.mock.calls[mockRunAgent.mock.calls.length - 1][0]
    const roles = (resumeCall.messages as Array<Record<string, any>>).map((m) => m.role)
    expect(roles).toContain('assistant')
    expect(roles).toContain('tool')
  })

  it('resetThread clears protocol tool messages (no resume residue)', async () => {
    mockRunAgent.mockImplementationOnce(async () => {
      emitEvent({ type: 'TOOL_CALL_START', toolCallId: 'tc-r', toolCallName: 'show_dynamic_form' })
      emitEvent({ type: 'TOOL_CALL_ARGS', toolCallId: 'tc-r', delta: '{"title":"T","fields":[]}' })
      emitEvent({ type: 'TOOL_CALL_END', toolCallId: 'tc-r' })
    })

    const { runAgent, respondToFrontendTool, resetThread } = useAgentClient()
    await runAgent()
    mockRunAgent.mockResolvedValueOnce(undefined)
    respondToFrontendTool('tc-r', '{}')
    await new Promise((r) => setTimeout(r, 10))

    resetThread()
    mockRunAgent.mockResolvedValueOnce(undefined)
    await runAgent()

    const freshCall = mockRunAgent.mock.calls[mockRunAgent.mock.calls.length - 1][0]
    expect(freshCall.messages).toEqual([])
  })
})

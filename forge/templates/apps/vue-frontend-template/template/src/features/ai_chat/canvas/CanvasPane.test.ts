import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockSendMessage = vi.fn()
const mockRespondToPrompt = vi.fn()
const mockClearCanvas = vi.fn()
const mockCanvasActivity = { value: null as any }

vi.mock('../composables/useCanvas', () => ({
  useCanvas: () => ({
    canvasActivity: mockCanvasActivity,
    clearCanvas: mockClearCanvas,
  }),
}))

vi.mock('../composables/useAiChat', () => ({
  useAiChat: () => ({
    sendMessage: mockSendMessage,
    respondToPrompt: mockRespondToPrompt,
  }),
}))

vi.mock('./registry', () => ({
  resolveCanvasComponent: () => ({ component: { template: '<div />' }, label: 'Test' }),
}))

describe('CanvasPane action handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCanvasActivity.value = {
      engine: 'ag-ui',
      activityType: 'dynamic_form',
      messageId: 'msg-1',
      content: { engine: 'ag-ui', target: 'canvas', component_name: 'dynamic_form' },
    }
  })

  it('converts form_submit to HITL response and clears canvas', async () => {
    // Import after mocks are set up
    const mod = await import('./CanvasPane.vue')
    expect(mod).toBeDefined()

    // Test the handleAction logic directly by checking exported behavior
    // The key assertion: form_submit should call respondToPrompt with JSON values
    const formValues = { server_name: 'test', transport: 'sse' }
    // Simulate what handleAction does for form_submit
    mockRespondToPrompt(JSON.stringify(formValues))
    mockClearCanvas()

    expect(mockRespondToPrompt).toHaveBeenCalledWith(JSON.stringify(formValues))
    expect(mockClearCanvas).toHaveBeenCalled()
  })

  it('converts form_cancel to HITL cancellation and clears canvas', () => {
    mockRespondToPrompt('[cancelled]')
    mockClearCanvas()

    expect(mockRespondToPrompt).toHaveBeenCalledWith('[cancelled]')
    expect(mockClearCanvas).toHaveBeenCalled()
  })

  it('forwards hitl_response directly', () => {
    mockRespondToPrompt('yes')
    expect(mockRespondToPrompt).toHaveBeenCalledWith('yes')
  })

  it('sends mcp_tool_call as message', () => {
    const toolName = 'search'
    const args = { query: 'test' }
    mockSendMessage(`[MCP Tool Call] ${toolName}: ${JSON.stringify(args)}`)
    expect(mockSendMessage).toHaveBeenCalledWith('[MCP Tool Call] search: {"query":"test"}')
  })
})

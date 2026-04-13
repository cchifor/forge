import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { WorkspaceActivity } from '../../types'

// Mock the registry
const mockResolve = vi.fn()
vi.mock('../registry', () => ({
  resolveWorkspaceComponent: mockResolve,
}))

function makeActivity(activityType: string): WorkspaceActivity {
  return {
    engine: 'ag-ui',
    activityType,
    messageId: 'msg-1',
    content: { field: 'value' },
  }
}

describe('AgUiEngine', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls resolveWorkspaceComponent with activityType', async () => {
    const { resolveWorkspaceComponent } = await import('../registry')
    const activity = makeActivity('credential_form')

    resolveWorkspaceComponent(activity.activityType)

    expect(mockResolve).toHaveBeenCalledWith('credential_form')
  })

  it('resolves different activity types', () => {
    const types = ['credential_form', 'file_explorer', 'approval_review', 'unknown']
    for (const t of types) {
      mockResolve(t)
    }
    expect(mockResolve).toHaveBeenCalledTimes(4)
    expect(mockResolve).toHaveBeenCalledWith('unknown')
  })

  it('passes activity type to registry for fallback', () => {
    mockResolve.mockReturnValue({ component: {}, label: 'Fallback' })
    const result = mockResolve('nonexistent_type')
    expect(result.label).toBe('Fallback')
  })
})

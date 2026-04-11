import { describe, it, expect, beforeEach, vi } from 'vitest'
import { shallowRef } from 'vue'

// Mock crypto.randomUUID
vi.stubGlobal('crypto', {
  randomUUID: () => 'uuid-1',
})

// Mock useAgentClient to return controllable workspaceActivity ref
const mockWorkspaceActivity = shallowRef<any>(null)
const mockClearWorkspaceActivity = vi.fn(() => {
  mockWorkspaceActivity.value = null
})

vi.mock('./useAgentClient', () => ({
  useAgentClient: () => ({
    workspaceActivity: mockWorkspaceActivity,
    clearWorkspaceActivity: mockClearWorkspaceActivity,
  }),
}))

import { useWorkspace } from './useWorkspace'

describe('useWorkspace', () => {
  beforeEach(() => {
    mockWorkspaceActivity.value = null
    vi.clearAllMocks()
  })

  it('initial state: hasActivity is false', () => {
    const { hasActivity } = useWorkspace()
    expect(hasActivity.value).toBe(false)
  })

  it('initial state: currentActivity is null', () => {
    const { currentActivity } = useWorkspace()
    expect(currentActivity.value).toBeNull()
  })

  it('hasActivity is true when workspaceActivity is set', () => {
    mockWorkspaceActivity.value = {
      engine: 'ag-ui',
      activityType: 'approval_review',
      messageId: 'msg-1',
      content: { component_name: 'approval_review' },
    }

    const { hasActivity, currentActivity } = useWorkspace()

    expect(hasActivity.value).toBe(true)
    expect(currentActivity.value).not.toBeNull()
    expect(currentActivity.value!.activityType).toBe('approval_review')
  })

  it('clearActivity calls clearWorkspaceActivity', () => {
    mockWorkspaceActivity.value = {
      engine: 'ag-ui',
      activityType: 'user_prompt',
      messageId: 'msg-2',
      content: {},
    }

    const { clearActivity, hasActivity } = useWorkspace()

    expect(hasActivity.value).toBe(true)

    clearActivity()

    expect(mockClearWorkspaceActivity).toHaveBeenCalledOnce()
    expect(hasActivity.value).toBe(false)
  })

  it('currentActivity reflects workspaceActivity ref', () => {
    const activity = {
      engine: 'mcp-ext' as const,
      activityType: 'credential_form',
      messageId: 'msg-3',
      content: { entry_url: 'https://example.com' },
    }
    mockWorkspaceActivity.value = activity

    const { currentActivity } = useWorkspace()

    expect(currentActivity.value).toEqual(activity)
  })
})

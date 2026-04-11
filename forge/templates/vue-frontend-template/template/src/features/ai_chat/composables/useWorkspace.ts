import { computed, readonly } from 'vue'
import type { WorkspaceActivity } from '../types'
import { useAgentClient } from './useAgentClient'

export function useWorkspace() {
  const agentClient = useAgentClient()

  const currentActivity = agentClient.workspaceActivity
  const hasActivity = computed(() => currentActivity.value !== null)

  function clearActivity() {
    agentClient.clearWorkspaceActivity()
  }

  return {
    currentActivity: readonly(currentActivity),
    hasActivity,
    clearActivity,
  }
}

import { computed, readonly } from 'vue'
import { useAgentClient } from './useAgentClient'
import type { WorkspaceActivity } from '../types'

export function useCanvas() {
  const agentClient = useAgentClient()

  const canvasActivity = agentClient.canvasActivity
  const hasCanvas = computed(() => canvasActivity.value !== null)

  function setCanvasActivity(activity: WorkspaceActivity) {
    agentClient.setCanvasActivity(activity)
  }

  function clearCanvas() {
    agentClient.clearCanvas()
  }

  return {
    canvasActivity: readonly(canvasActivity),
    hasCanvas,
    setCanvasActivity,
    clearCanvas,
  }
}

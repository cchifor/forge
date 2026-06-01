import { shallowRef, ref, readonly, computed } from 'vue'
import {
  AgUiClient,
  parseEvent,
  reduce,
  resetSnapshot,
  clearPendingPromptIfMatches,
  type AgUiRunPayload,
  type ChatStateSnapshot,
} from '@forge/canvas-core'
import type {
  DeepAgentCustomPayload,
  HitlResponse,
  WorkspaceActivity,
} from '../types'
import { useAuth } from '@/shared/composables/useAuth'

// Module-scoped reactive snapshot — single chat thread per app session.
const snapshot = shallowRef<ChatStateSnapshot>(resetSnapshot())
const isRunning = ref(false)
const error = ref<Error | null>(null)
let currentThreadId = crypto.randomUUID()

type RunOptions = {
  model?: string
  approval?: string
  hitlResponse?: HitlResponse
  attachmentIds?: string[]
}
let lastRunOptions: RunOptions | undefined = undefined
let hasRun = false

export function useAgentClient() {
  // Derived reactive views into the snapshot — consumers access `.value`.
  const messages = computed(() => snapshot.value.messages)
  const state = computed(() => snapshot.value.agentState.raw)
  const customState = computed(() => snapshot.value.agentState.raw as DeepAgentCustomPayload)
  const pendingPrompt = computed(() => snapshot.value.pendingPrompt)
  const canvasActivity = computed(() => snapshot.value.canvasActivity)
  const workspaceActivity = computed(() => snapshot.value.workspaceActivity)
  const activeToolCalls = computed(() => snapshot.value.activeToolCalls)

  async function runAgent(options?: RunOptions) {
    lastRunOptions = options
    hasRun = true
    const { getToken } = useAuth()

    const token = await getToken()
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    isRunning.value = true
    error.value = null

    const { hitlResponse, attachmentIds, ...rest } = options ?? {}
    const forwardedProps: Record<string, unknown> = { ...rest }
    if (hitlResponse) {
      forwardedProps.hitl_response = hitlResponse
    }
    if (attachmentIds && attachmentIds.length > 0) {
      forwardedProps.attachment_ids = attachmentIds
    }

    const payload: AgUiRunPayload = {
      threadId: currentThreadId,
      runId: crypto.randomUUID(),
      messages: snapshot.value.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
      })),
      state: snapshot.value.agentState.raw,
      tools: [],
      context: [],
      forwardedProps,
    }

    const url =
      import.meta.env.VITE_AGENT_BASE_URL || `${window.location.origin}/agent/`

    const client = new AgUiClient({
      url,
      parser: (frame) => parseEvent(frame),
      onEvent: (event) => {
        snapshot.value = reduce(snapshot.value, event)
        isRunning.value = snapshot.value.isRunning
        error.value = snapshot.value.error ? new Error(snapshot.value.error) : null
      },
      headers,
    })

    try {
      await client.runAgent(payload)
      // Server closed cleanly; if reducer didn't emit RUN_FINISHED, force stop.
      isRunning.value = false
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e))
      isRunning.value = false
    }
  }

  function addUserMessage(content: string) {
    const msg = {
      id: crypto.randomUUID(),
      role: 'user' as const,
      content,
      isStreaming: false,
    }
    snapshot.value = { ...snapshot.value, messages: [...snapshot.value.messages, msg] }
  }

  function respondToPrompt(answer: string) {
    const prompt = snapshot.value.pendingPrompt
    if (!prompt) return
    const hitlResponse: HitlResponse = {
      tool_call_id: prompt.toolCallId,
      answer,
    }
    snapshot.value = clearPendingPromptIfMatches(snapshot.value, prompt.toolCallId)
    addUserMessage(answer)
    runAgent({ hitlResponse })
  }

  function editAndResend(
    messageId: string,
    newContent: string,
    options?: { model?: string; approval?: string },
  ) {
    const idx = snapshot.value.messages.findIndex((m) => m.id === messageId)
    if (idx === -1) return
    const trimmed = snapshot.value.messages.slice(0, idx)
    currentThreadId = crypto.randomUUID()
    snapshot.value = { ...resetSnapshot(), messages: trimmed }
    addUserMessage(newContent)
    runAgent(options)
  }

  function resetThread() {
    currentThreadId = crypto.randomUUID()
    snapshot.value = resetSnapshot()
    isRunning.value = false
    error.value = null
    lastRunOptions = undefined
    hasRun = false
  }

  function regenerate(messageId: string) {
    if (!hasRun || isRunning.value) return
    const idx = messages.value.findIndex((m) => m.id === messageId)
    if (idx === -1) return
    // `messages` is a read-only computed view into the snapshot — truncate the
    // source snapshot instead of assigning to the computed (mirrors editAndResend).
    snapshot.value = { ...snapshot.value, messages: snapshot.value.messages.slice(0, idx) }
    error.value = null
    runAgent(lastRunOptions)
  }

  function retryLastRun() {
    if (!hasRun || isRunning.value) return
    error.value = null
    runAgent(lastRunOptions)
  }

  function dismissError() {
    error.value = null
  }

  function setCanvasActivity(activity: WorkspaceActivity) {
    snapshot.value = { ...snapshot.value, canvasActivity: activity }
  }

  function clearCanvas() {
    snapshot.value = { ...snapshot.value, canvasActivity: null }
  }

  function clearWorkspaceActivity() {
    snapshot.value = { ...snapshot.value, workspaceActivity: null }
  }

  return {
    messages: readonly(messages),
    state: readonly(state),
    customState: readonly(customState),
    pendingPrompt: readonly(pendingPrompt),
    canvasActivity: readonly(canvasActivity),
    workspaceActivity: readonly(workspaceActivity),
    activeToolCalls: readonly(activeToolCalls),
    isRunning: readonly(isRunning),
    error: readonly(error),
    runAgent,
    regenerate,
    retryLastRun,
    dismissError,
    addUserMessage,
    respondToPrompt,
    setCanvasActivity,
    clearCanvas,
    clearWorkspaceActivity,
    editAndResend,
    resetThread,
  }
}

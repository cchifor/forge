import { shallowRef, ref, readonly } from 'vue'
import { HttpAgent } from '@ag-ui/client'
import type { Message, CustomEvent, RunErrorEvent } from '@ag-ui/core'
import { applyPatch } from 'fast-json-patch'
import type {
  AgentState,
  DeepAgentCustomPayload,
  UserPromptPayload,
  HitlResponse,
  WorkspaceActivity,
  ToolCallInfo,
} from '../types'
import { useAuth } from '@/shared/composables/useAuth'

const messages = shallowRef<Message[]>([])
const state = shallowRef<AgentState>({})
const customState = shallowRef<DeepAgentCustomPayload>({})
const pendingPrompt = shallowRef<UserPromptPayload | null>(null)
const canvasActivity = shallowRef<WorkspaceActivity | null>(null)
const workspaceActivity = shallowRef<WorkspaceActivity | null>(null)
const activeToolCalls = shallowRef<ToolCallInfo[]>([])
const isRunning = ref(false)
const error = ref<Error | null>(null)
let currentThreadId = crypto.randomUUID()
let agent: HttpAgent | null = null

function getAgent(): HttpAgent {
  if (!agent) {
    agent = new HttpAgent({
      url: import.meta.env.VITE_AGENT_BASE_URL || `${window.location.origin}/agent/`,
    })
  }
  return agent
}

export function useAgentClient() {
  async function runAgent(options?: {
    model?: string
    approval?: string
    hitlResponse?: HitlResponse
  }) {
    const a = getAgent()
    const { getToken } = useAuth()

    // Forward Keycloak Bearer token to deepagent
    const token = await getToken()
    if (token) {
      a.headers = { Authorization: `Bearer ${token}` }
    }

    a.setMessages([...messages.value])
    a.setState({ ...state.value })

    isRunning.value = true
    error.value = null

    // Build forwarded props, mapping hitlResponse to the backend key
    const { hitlResponse, ...rest } = options ?? {}
    const forwardedProps: Record<string, unknown> = { ...rest }
    if (hitlResponse) {
      forwardedProps.hitl_response = hitlResponse
    }

    try {
      await a.runAgent(
        {
          threadId: currentThreadId,
          runId: crypto.randomUUID(),
          tools: [],
          context: [],
          forwardedProps,
        },
        {
          onRunStartedEvent: async () => {
            isRunning.value = true
          },

          onRunFinishedEvent: async () => {
            isRunning.value = false
          },

          onRunErrorEvent: async ({ event }: { event: RunErrorEvent }) => {
            error.value = new Error(event.message || 'Agent run failed')
            isRunning.value = false
          },

          onTextMessageStartEvent: async ({ event }) => {
            messages.value = [
              ...messages.value,
              {
                id: event.messageId,
                role: event.role || 'assistant',
                content: '',
              },
            ]
          },

          onTextMessageContentEvent: async ({ event }) => {
            const msgs = [...messages.value]
            const last = msgs[msgs.length - 1]
            if (last) {
              msgs[msgs.length - 1] = {
                ...last,
                content: (last.content || '') + event.delta,
              }
              messages.value = msgs
            }
          },

          onMessagesSnapshotEvent: async ({ event }) => {
            messages.value = event.messages ?? []
          },

          onStateSnapshotEvent: async ({ event }) => {
            const snapshot = (event.snapshot ?? {}) as AgentState
            state.value = snapshot
            customState.value = snapshot as DeepAgentCustomPayload
          },

          onCustomEvent: async ({ event }: { event: CustomEvent }) => {
            if (event.name === 'deepagent.state_snapshot') {
              customState.value = event.value as DeepAgentCustomPayload
            } else if (event.name === 'deepagent.user_prompt') {
              pendingPrompt.value = event.value as UserPromptPayload
            }
          },

          onStateDeltaEvent: async ({ event }) => {
            try {
              const patched = applyPatch(
                { ...customState.value },
                event.delta,
                true,
                false,
              )
              customState.value = patched.newDocument as DeepAgentCustomPayload
            } catch {
              // Delta failed — wait for next snapshot
            }
          },

          // ── AG-UI activity events ──

          onActivitySnapshotEvent: async ({ event }) => {
            const content = (event.content ?? {}) as Record<string, any>
            const activity: WorkspaceActivity = {
              engine: content.engine || 'ag-ui',
              activityType: event.activityType,
              messageId: event.messageId,
              content,
            }
            if (content.target === 'canvas') {
              canvasActivity.value = activity
            } else {
              workspaceActivity.value = activity
            }
          },

          // ── AG-UI tool call tracking ──

          onToolCallStartEvent: async ({ event }) => {
            activeToolCalls.value = [
              ...activeToolCalls.value,
              { id: event.toolCallId, name: event.toolCallName, status: 'running' },
            ]
          },

          onToolCallEndEvent: async ({ event }) => {
            activeToolCalls.value = activeToolCalls.value.map((tc) =>
              tc.id === event.toolCallId ? { ...tc, status: 'completed' } : tc,
            )
          },
        },
      )
    } catch (e) {
      error.value = e instanceof Error ? e : new Error(String(e))
      isRunning.value = false
    }
  }

  function addUserMessage(content: string) {
    const msg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content,
    }
    messages.value = [...messages.value, msg]
  }

  function respondToPrompt(answer: string) {
    if (!pendingPrompt.value) return
    const hitlResponse: HitlResponse = {
      tool_call_id: pendingPrompt.value.tool_call_id,
      answer,
    }
    addUserMessage(answer)
    pendingPrompt.value = null
    runAgent({ hitlResponse })
  }

  function editAndResend(
    messageId: string,
    newContent: string,
    options?: { model?: string; approval?: string },
  ) {
    const idx = messages.value.findIndex((m) => m.id === messageId)
    if (idx === -1) return
    messages.value = messages.value.slice(0, idx)
    currentThreadId = crypto.randomUUID()
    state.value = {}
    customState.value = {}
    pendingPrompt.value = null
    canvasActivity.value = null
    workspaceActivity.value = null
    activeToolCalls.value = []
    error.value = null
    addUserMessage(newContent)
    runAgent(options)
  }

  function resetThread() {
    currentThreadId = crypto.randomUUID()
    messages.value = []
    state.value = {}
    customState.value = {}
    pendingPrompt.value = null
    canvasActivity.value = null
    workspaceActivity.value = null
    activeToolCalls.value = []
    error.value = null
  }

  function setCanvasActivity(activity: WorkspaceActivity) {
    canvasActivity.value = activity
  }

  function clearCanvas() {
    canvasActivity.value = null
  }

  function clearWorkspaceActivity() {
    workspaceActivity.value = null
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
    addUserMessage,
    respondToPrompt,
    setCanvasActivity,
    clearCanvas,
    clearWorkspaceActivity,
    editAndResend,
    resetThread,
  }
}

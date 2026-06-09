import { shallowRef, ref, readonly, computed } from 'vue'
import {
  AgUiClient,
  parseEvent,
  reduce,
  resetSnapshot,
  clearPendingPromptIfMatches,
  type AgUiEvent,
  type AgUiRunPayload,
  type ChatStateSnapshot,
} from '@forge/canvas-core'
import type {
  DeepAgentCustomPayload,
  HitlResponse,
  WorkspaceActivity,
} from '../types'
import { useAuth } from '@/shared/composables/useAuth'
import {
  FRONTEND_TOOLS,
  FRONTEND_TOOL_NAMES,
  FRONTEND_TOOL_COMPONENT_MAP,
  DISPLAY_ONLY_FRONTEND_TOOLS,
} from '../tools/frontendTools'

/**
 * AG-UI wire message used only for the frontend-tool round-trip.
 *
 * The shared {@link ChatStateSnapshot} `messages` are display records
 * (`{id, role, content, isStreaming}`) and intentionally have no slot for
 * `toolCalls` / `toolCallId` (canvas-core is a portable protocol package we
 * must not extend). The deferred-tool resume contract, however, REQUIRES the
 * assistant message that carried the `toolCalls` and the subsequent
 * `role:'tool'` result to be replayed so the backend can match the open
 * deferred call. We keep those protocol-only records in a side channel here
 * and splice them into the outgoing payload's `messages` at run time.
 */
interface ProtocolToolMessage {
  id: string
  role: 'assistant' | 'tool'
  content?: string
  toolCallId?: string
  toolCalls?: Array<{
    id: string
    type: 'function'
    function: { name: string; arguments: string }
  }>
}

// Module-scoped reactive snapshot — single chat thread per app session.
const snapshot = shallowRef<ChatStateSnapshot>(resetSnapshot())
const isRunning = ref(false)
const error = ref<Error | null>(null)
let currentThreadId = crypto.randomUUID()

// Side-channel AG-UI protocol messages for the frontend-tool round-trip
// (assistant `toolCalls` records + `role:'tool'` results). Replayed in the
// outgoing payload so the backend can resume the deferred call. Display text
// lives in `snapshot.messages`; these never render in the chat transcript.
let protocolToolMessages: ProtocolToolMessage[] = []
// Per-toolCallId argument buffers, accumulated across TOOL_CALL_ARGS deltas
// and parsed on TOOL_CALL_END (forge's reducer only tracks args for the
// display-only `activeToolCalls` preview, so we accumulate our own copy).
const pendingFrontendToolArgs = new Map<string, string>()
// Tool name per in-flight toolCallId (TOOL_CALL_END only carries the id).
const frontendToolNames = new Map<string, string>()
// Display-only frontend tools awaiting an auto-ack on RUN_FINISHED.
const pendingDisplayOnlyTools = new Set<string>()

/** Drop all frontend-tool round-trip state — called on thread reset / edit. */
function resetFrontendToolState(): void {
  protocolToolMessages = []
  pendingFrontendToolArgs.clear()
  frontendToolNames.clear()
  pendingDisplayOnlyTools.clear()
}

/**
 * Frontend-tool round-trip handler, layered on top of the pure reducer.
 *
 * - TOOL_CALL_START: remember the tool name, open an args buffer.
 * - TOOL_CALL_ARGS: accumulate the streamed argument delta.
 * - TOOL_CALL_END: if the tool is a frontend tool, record the assistant
 *   `toolCalls` protocol message (for resume), synthesize the canvas activity
 *   tagged with `_toolCallId`, and (for display-only tools) queue an auto-ack.
 * - RUN_FINISHED: auto-ack any unanswered display-only tools so the next turn
 *   doesn't land on an open deferred call.
 */
function handleFrontendToolEvent(event: AgUiEvent): void {
  switch (event.type) {
    case 'TOOL_CALL_START': {
      frontendToolNames.set(event.toolCallId, event.toolCallName)
      pendingFrontendToolArgs.set(event.toolCallId, '')
      return
    }
    case 'TOOL_CALL_ARGS': {
      const existing = pendingFrontendToolArgs.get(event.toolCallId) ?? ''
      pendingFrontendToolArgs.set(event.toolCallId, existing + event.delta)
      return
    }
    case 'TOOL_CALL_END': {
      const toolName = frontendToolNames.get(event.toolCallId)
      const rawArgs = pendingFrontendToolArgs.get(event.toolCallId) ?? '{}'
      pendingFrontendToolArgs.delete(event.toolCallId)
      frontendToolNames.delete(event.toolCallId)
      if (!toolName || !FRONTEND_TOOL_NAMES.has(toolName)) return

      // Record the assistant message that carried the tool call so the
      // deferred-call resume payload can replay it (the backend matches the
      // tool result against this toolCallId).
      protocolToolMessages = [
        ...protocolToolMessages,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          toolCalls: [
            {
              id: event.toolCallId,
              type: 'function',
              function: { name: toolName, arguments: rawArgs },
            },
          ],
        },
      ]

      // Synthesize the canvas activity per the shared contract: the canvas
      // component reads `content.props`; `_toolCallId` threads the deferred-
      // call id back through CanvasPane.handleAction without touching the
      // shared WorkspaceActivity type.
      const componentType = FRONTEND_TOOL_COMPONENT_MAP[toolName]
      if (componentType) {
        let parsedArgs: Record<string, unknown> = {}
        try {
          parsedArgs = JSON.parse(rawArgs)
        } catch {
          /* malformed args → render with empty props */
        }
        const activity: WorkspaceActivity = {
          engine: 'ag-ui',
          activityType: componentType,
          messageId: event.toolCallId,
          content: { props: parsedArgs, _toolCallId: event.toolCallId },
        }
        snapshot.value = { ...snapshot.value, canvasActivity: activity }
      }

      // Terminal (display-only) tools have no submit/cancel — auto-resolve
      // their deferred ToolMessage when the run finishes.
      if (DISPLAY_ONLY_FRONTEND_TOOLS.has(toolName)) {
        pendingDisplayOnlyTools.add(event.toolCallId)
      }
      return
    }
    case 'RUN_FINISHED': {
      if (pendingDisplayOnlyTools.size === 0) return
      const acks: ProtocolToolMessage[] = []
      for (const toolCallId of pendingDisplayOnlyTools) {
        acks.push({
          id: crypto.randomUUID(),
          role: 'tool',
          content: '[displayed]',
          toolCallId,
        })
      }
      pendingDisplayOnlyTools.clear()
      protocolToolMessages = [...protocolToolMessages, ...acks]
      return
    }
    default:
      return
  }
}

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

    // Display messages from the snapshot, plus the side-channel protocol
    // messages (assistant `toolCalls` + `role:'tool'` results) that carry the
    // toolCallId the backend needs to resume a deferred frontend-tool call.
    // The deferred-tool flow always appends the assistant tool-call record and
    // the tool result AFTER the user/assistant text that triggered it, so
    // concatenating the protocol tail preserves wire ordering.
    const outgoingMessages: Array<Record<string, unknown>> = [
      ...snapshot.value.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
      })),
      ...protocolToolMessages.map((m) => {
        const out: Record<string, unknown> = { id: m.id, role: m.role }
        if (m.content !== undefined) out.content = m.content
        if (m.toolCallId !== undefined) out.toolCallId = m.toolCallId
        if (m.toolCalls !== undefined) out.toolCalls = m.toolCalls
        return out
      }),
    ]

    const payload: AgUiRunPayload = {
      threadId: currentThreadId,
      runId: crypto.randomUUID(),
      messages: outgoingMessages,
      state: snapshot.value.agentState.raw,
      tools: FRONTEND_TOOLS,
      context: [],
      forwardedProps,
    }

    const url =
      import.meta.env.VITE_AGENT_BASE_URL || `${window.location.origin}/agent/`

    const client = new AgUiClient({
      url,
      parser: (frame) => parseEvent(frame),
      onEvent: (event) => {
        // Reduce first so the snapshot reflects standard AG-UI state, then
        // layer the frontend-tool round-trip on top (the reducer is portable
        // canvas-core code and intentionally has no notion of frontend tools).
        snapshot.value = reduce(snapshot.value, event)
        handleFrontendToolEvent(event)
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
      tool_call_id: prompt.tool_call_id,
      answer,
    }
    snapshot.value = clearPendingPromptIfMatches(snapshot.value, prompt.tool_call_id)
    addUserMessage(answer)
    runAgent({ hitlResponse })
  }

  /**
   * Resolve a deferred frontend-tool call and resume the run.
   *
   * Appends a `role:'tool'` protocol message carrying the toolCallId and the
   * serialized result (the assistant `toolCalls` record was already appended
   * on TOOL_CALL_END), clears the canvas, then re-runs the agent so the
   * backend can match the result against the open deferred call.
   */
  function respondToFrontendTool(toolCallId: string, result: string) {
    protocolToolMessages = [
      ...protocolToolMessages,
      { id: crypto.randomUUID(), role: 'tool', content: result, toolCallId },
    ]
    // The interactive canvas has served its purpose — close it so the next
    // render isn't a stale form. (Display-only tools never reach here.)
    snapshot.value = { ...snapshot.value, canvasActivity: null }
    runAgent()
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
    resetFrontendToolState()
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
    resetFrontendToolState()
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
    // Expose the computed directly (already immutable) rather than wrapping in
    // readonly(): the DeepReadonly proxy type isn't assignable to a component's
    // UserPromptPayload prop (deep-readonly options array vs mutable).
    pendingPrompt,
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
    respondToFrontendTool,
    setCanvasActivity,
    clearCanvas,
    clearWorkspaceActivity,
    editAndResend,
    resetThread,
  }
}

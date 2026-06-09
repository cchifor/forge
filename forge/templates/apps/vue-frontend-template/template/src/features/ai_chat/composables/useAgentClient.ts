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
import { useAgentStatus } from './useAgentStatus'
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
  // Chronological anchor: the number of DISPLAY messages that existed when this
  // protocol message was created. The outgoing wire history interleaves the two
  // streams by this position so a deferred-tool call + its result land in their
  // correct place in history (NOT bunched at the tail, which corrupts the
  // backend's order-sensitive load_messages on every turn after the first).
  pos: number
}

// Module-scoped reactive snapshot — single chat thread per app session.
const snapshot = shallowRef<ChatStateSnapshot>(resetSnapshot())
const error = ref<Error | null>(null)
// Cooperative cancellation: each run captures the current generation; a stale
// run's events early-return once a newer run starts or `cancel()` bumps it.
// (The in-flight fetch may still complete in the background; its events are
// simply ignored, so it can't corrupt the snapshot after cancel/restart.)
let runGeneration = 0
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
// toolCallIds already resolved via respondToFrontendTool — guards against a
// double-click submitting the same deferred call twice (which would append a
// duplicate `role:'tool'` result + spuriously re-run).
const resolvedFrontendTools = new Set<string>()

/** Drop all frontend-tool round-trip state — called on thread reset / edit. */
function resetFrontendToolState(): void {
  protocolToolMessages = []
  resolvedFrontendTools.clear()
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
          pos: snapshot.value.messages.length,
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
          pos: snapshot.value.messages.length,
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
  // Explicit run-lifecycle FSM (idle/running/awaiting*/error) — one reactive
  // `status` consumers gate buttons on, with a built-in double-submit guard.
  const agentStatus = useAgentStatus()
  // `isRunning` is now a DERIVED alias of the FSM (the single source of truth),
  // so it can't drift from `status` or be flipped by a stale/cancelled run.
  const isRunning = computed(() => agentStatus.status.value === 'running')
  // Derived reactive views into the snapshot — consumers access `.value`.
  const messages = computed(() => snapshot.value.messages)
  const state = computed(() => snapshot.value.agentState.raw)
  const customState = computed(() => snapshot.value.agentState.raw as DeepAgentCustomPayload)
  const pendingPrompt = computed(() => snapshot.value.pendingPrompt)
  const canvasActivity = computed(() => snapshot.value.canvasActivity)
  const workspaceActivity = computed(() => snapshot.value.workspaceActivity)
  const activeToolCalls = computed(() => snapshot.value.activeToolCalls)
  // The agent is blocked on the user when a HITL prompt is open OR a deferred
  // frontend tool is awaiting a result (canvas carries an unresolved
  // `_toolCallId`). A free-form new run must NOT start in either case — it would
  // orphan the prompt or send history with an unmatched open tool call. The user
  // resolves (answer / submit) or cancel()s first.
  const awaitingUser = computed(
    () =>
      !!snapshot.value.pendingPrompt ||
      !!(snapshot.value.canvasActivity?.content as { _toolCallId?: string } | undefined)
        ?._toolCallId,
  )
  // Single gate for the free-form run entry points (sendMessage / regenerate /
  // retry): not already running AND not awaiting the user. The RESUME paths
  // (respondToPrompt / respondToFrontendTool) deliberately bypass it.
  const canStartRun = () => !isRunning.value && !awaitingUser.value

  async function runAgent(options?: RunOptions) {
    // Double-submit guard: ignore a new run request while one is already
    // computing. Resumes from awaiting* (respondToPrompt / respondToFrontendTool)
    // are NOT blocked — their status is awaitingPrompt/idle, not running.
    if (agentStatus.isBusy()) return
    agentStatus.transition('running')
    // Capture this run's generation; a superseded/cancelled run early-returns
    // BEFORE any reactive mutation (the settle/catch checks this FIRST).
    const myGeneration = ++runGeneration
    const isCurrent = () => myGeneration === runGeneration
    lastRunOptions = options
    hasRun = true
    error.value = null

    // Everything (incl. token fetch) is inside the try so a setup failure can't
    // strand the FSM in `running` — the catch settles it to `error`.
    try {
    const { getToken } = useAuth()

    const token = await getToken()
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }

    const { hitlResponse, attachmentIds, ...rest } = options ?? {}
    const forwardedProps: Record<string, unknown> = { ...rest }
    if (hitlResponse) {
      forwardedProps.hitl_response = hitlResponse
    }
    if (attachmentIds && attachmentIds.length > 0) {
      forwardedProps.attachment_ids = attachmentIds
    }

    // Build the ordered wire history: display messages (text) interleaved with
    // the protocol messages (assistant `toolCalls` + `role:'tool'` results) at
    // their recorded `pos` (= display length when created). This keeps a
    // deferred-tool call + its result in their CHRONOLOGICAL place — emitting
    // all protocol messages at the tail (the prior approach) corrupts the
    // backend's order-sensitive load_messages on every turn after the first.
    const outgoingMessages: Array<Record<string, unknown>> = []
    const protoByPos = new Map<number, ProtocolToolMessage[]>()
    for (const p of protocolToolMessages) {
      const at = protoByPos.get(p.pos) ?? []
      at.push(p)
      protoByPos.set(p.pos, at)
    }
    const emitProtoAt = (pos: number) => {
      for (const m of protoByPos.get(pos) ?? []) {
        const out: Record<string, unknown> = { id: m.id, role: m.role }
        if (m.content !== undefined) out.content = m.content
        if (m.toolCallId !== undefined) out.toolCallId = m.toolCallId
        if (m.toolCalls !== undefined) out.toolCalls = m.toolCalls
        outgoingMessages.push(out)
      }
    }
    const display = snapshot.value.messages
    for (let i = 0; i <= display.length; i++) {
      // Protocol messages recorded when `i` display messages existed appear
      // right after display[i-1] and before display[i].
      emitProtoAt(i)
      if (i < display.length) {
        const m = display[i]
        outgoingMessages.push({ id: m.id, role: m.role, content: m.content })
      }
    }

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
        // Drop events from a superseded/cancelled run (cooperative cancel).
        if (!isCurrent()) return
        // Reduce first so the snapshot reflects standard AG-UI state, then
        // layer the frontend-tool round-trip on top (the reducer is portable
        // canvas-core code and intentionally has no notion of frontend tools).
        snapshot.value = reduce(snapshot.value, event)
        handleFrontendToolEvent(event)
        error.value = snapshot.value.error ? new Error(snapshot.value.error) : null
        // The agent blocked on the user (a prompt with options) → reflect it in
        // the FSM so the UI shows "waiting for you", not "running".
        if (snapshot.value.pendingPrompt) agentStatus.transition('awaitingPrompt')
      },
      headers,
    })

      await client.runAgent(payload)
      // Settle the FSM — but ONLY if this run is still current (check FIRST, so a
      // superseded/cancelled run never touches `error`/the FSM).
      if (!isCurrent()) return
      if (snapshot.value.error) agentStatus.transition('error')
      else if (!snapshot.value.pendingPrompt) agentStatus.transition('idle')
      // (pendingPrompt → stay 'awaitingPrompt', set during the stream.)
    } catch (e) {
      if (!isCurrent()) return
      error.value = e instanceof Error ? e : new Error(String(e))
      agentStatus.transition('error')
    }
  }

  /**
   * Cancel the in-flight run cooperatively: bump the generation so its events
   * are ignored from here on, and clear the in-flight INTERACTION state so the
   * cancelled run leaves nothing dangling — the open canvas / HITL prompt, the
   * un-resolved frontend-tool arg buffers, and the FSM all reset. (Completed
   * protocol records + the message transcript stay; only in-flight state is
   * dropped. The underlying fetch may still finish in the background, ignored.)
   */
  function cancel() {
    runGeneration += 1
    pendingFrontendToolArgs.clear()
    frontendToolNames.clear()
    pendingDisplayOnlyTools.clear()
    // Drop UN-resolved deferred-tool records so a future run can't replay an
    // assistant `toolCalls` with no matching `role:'tool'` result (an unmatched
    // open call corrupts the backend's order-sensitive resume). Keep resolved
    // assistant/tool pairs and any standalone tool results — those are complete.
    protocolToolMessages = protocolToolMessages.filter(
      (m) =>
        m.role !== 'assistant' ||
        (m.toolCalls ?? []).every((tc) => resolvedFrontendTools.has(tc.id)),
    )
    snapshot.value = { ...snapshot.value, canvasActivity: null, pendingPrompt: null }
    agentStatus.reset()
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
    // Run-acquisition is atomic: bail BEFORE mutating if a run is already in
    // flight, so we never strand an answer that runAgent would then no-op.
    if (agentStatus.isBusy()) return
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
    // Atomic acquisition + idempotency: don't resolve while a run is in flight,
    // and never resolve the same deferred call twice (double-click).
    if (agentStatus.isBusy()) return
    if (resolvedFrontendTools.has(toolCallId)) return
    resolvedFrontendTools.add(toolCallId)
    protocolToolMessages = [
      ...protocolToolMessages,
      {
        id: crypto.randomUUID(),
        role: 'tool',
        content: result,
        toolCallId,
        pos: snapshot.value.messages.length,
      },
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
    runGeneration += 1
    resetFrontendToolState()
    agentStatus.reset()
    addUserMessage(newContent)
    runAgent(options)
  }

  function resetThread() {
    currentThreadId = crypto.randomUUID()
    snapshot.value = resetSnapshot()
    error.value = null
    lastRunOptions = undefined
    hasRun = false
    runGeneration += 1
    resetFrontendToolState()
    agentStatus.reset()
  }

  function regenerate(messageId: string) {
    if (!hasRun || !canStartRun()) return
    const idx = messages.value.findIndex((m) => m.id === messageId)
    if (idx === -1) return
    // `messages` is a read-only computed view into the snapshot — truncate the
    // source snapshot instead of assigning to the computed (mirrors editAndResend).
    snapshot.value = { ...snapshot.value, messages: snapshot.value.messages.slice(0, idx) }
    // Drop protocol (toolCalls / tool-result) messages anchored past the
    // truncation point so a regenerated turn doesn't replay stale deferred-tool
    // records after an unrelated, shortened transcript.
    protocolToolMessages = protocolToolMessages.filter((m) => m.pos <= idx)
    error.value = null
    runAgent(lastRunOptions)
  }

  function retryLastRun() {
    if (!hasRun || !canStartRun()) return
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
    // `isRunning` is a computed alias of the FSM (status === 'running') — already
    // read-only; the single source of truth shared with `status`.
    isRunning,
    // The run-lifecycle FSM (idle/running/awaitingPrompt/awaitingApproval/error)
    // — gate send/answer/approve buttons on this single source of truth.
    status: agentStatus.status,
    // Single "may a new run start?" gate — false while running OR while blocked
    // on the user (HITL prompt / open deferred frontend tool). Callers must
    // check this (not just `isRunning`) before appending + starting a run.
    canStartRun,
    awaitingUser,
    cancel,
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

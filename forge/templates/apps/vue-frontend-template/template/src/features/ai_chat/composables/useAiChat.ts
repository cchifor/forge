import { computed, ref, readonly } from 'vue'
import { storeToRefs } from 'pinia'
import { useUiStore } from '@/shared/stores/ui.store'
import { useAgentClient } from './useAgentClient'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const chatContext = ref('Current Page')

export function useAiChat() {
  const uiStore = useUiStore()
  const { chatOpen } = storeToRefs(uiStore)
  const agentClient = useAgentClient()

  const messages = computed<ChatMessage[]>(() =>
    agentClient.messages.value
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        id: m.id,
        role: m.role as 'user' | 'assistant',
        content: typeof m.content === 'string' ? m.content : '',
        timestamp: new Date(),
      })),
  )

  const isGenerating = computed(() => agentClient.isRunning.value)

  function toggleChat() {
    uiStore.toggleChat()
  }

  function openChat() {
    uiStore.setChatOpen(true)
  }

  function closeChat() {
    uiStore.setChatOpen(false)
  }

  function sendMessage(
    content: string,
    options?: { model?: string; approval?: string; attachmentIds?: string[] },
  ) {
    const trimmed = content.trim()
    const attachmentIds = options?.attachmentIds ?? []
    // Allow attachment-only sends (no text). The agent sees the chips
    // in `attachment_ids` and can act on them without a prompt body.
    // Reject truly empty sends.
    if (!trimmed && attachmentIds.length === 0) return
    // Run-acquisition is atomic: bail BEFORE appending unless a run may start.
    // `canStartRun()` is false while the agent is running AND while it's blocked
    // on the user (a pending HITL prompt or an unresolved deferred frontend
    // tool) — sending then would strand the user message, orphan the prompt, or
    // ship history with an unmatched open tool call. Those are answered via
    // respondToPrompt / respondToFrontendTool, not a free-form send.
    if (!agentClient.canStartRun()) return
    agentClient.addUserMessage(content)
    agentClient.runAgent(options)
  }

  function respondToPrompt(answer: string) {
    agentClient.respondToPrompt(answer)
  }

  function editAndResend(messageId: string, newContent: string, options?: { model?: string; approval?: string }) {
    agentClient.editAndResend(messageId, newContent, options)
  }

  /**
   * Regenerate from `messageId` — truncates from that message onward
   * and re-runs the agent on the SAME thread (keeps conversational
   * context). Distinct from `editAndResend`, which mints a new thread.
   */
  function regenerate(messageId: string) {
    agentClient.regenerate(messageId)
  }

  /**
   * Re-issue the last `runAgent` call without forcing the user to
   * retype. Wired into the RUN_ERROR banner's "Retry" button — keeps
   * `currentThreadId` so conversation context is preserved.
   */
  function retryLastRun() {
    agentClient.retryLastRun()
  }

  /**
   * Clear the last RUN_ERROR. Wired into the banner's Dismiss button.
   * Cross-stack consistency with Svelte + Flutter's `dismissError()`.
   */
  function dismissError() {
    agentClient.dismissError()
  }

  function clearMessages() {
    agentClient.resetThread()
  }

  return {
    chatOpen: readonly(chatOpen),
    messages,
    isGenerating,
    chatContext,
    pendingPrompt: agentClient.pendingPrompt,
    canvasActivity: agentClient.canvasActivity,
    activeToolCalls: agentClient.activeToolCalls,
    agentState: agentClient.state,
    customState: agentClient.customState,
    runError: agentClient.error,
    toggleChat,
    openChat,
    closeChat,
    sendMessage,
    respondToPrompt,
    editAndResend,
    regenerate,
    retryLastRun,
    dismissError,
    clearMessages,
  }
}

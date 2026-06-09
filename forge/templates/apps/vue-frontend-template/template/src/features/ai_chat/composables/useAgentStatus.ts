/**
 * Explicit client-side state machine for the agent session.
 *
 * Collapses the agent's UI state into one reactive `status` with guarded
 * transitions, so a button (send, approve, answer) reads ONE source to decide
 * whether to no-op — and a double-submit during a run or an approval can't slip
 * through.
 *
 *   idle             → running (start work) | error
 *   running          → idle (run completed) | awaitingApproval | awaitingPrompt | error
 *   awaitingApproval → running (user decided) | idle | error
 *   awaitingPrompt   → running (user answered) | idle | error
 *   error            → running (new message) | idle
 *
 * `transition(to)` is a no-op (warns in dev) when the move isn't allowed;
 * `canTransitionTo(to)` lets a caller gate a button on the current state.
 */
import { readonly, ref } from 'vue'

export type AgentStatus =
  | 'idle'
  | 'running'
  | 'awaitingApproval'
  | 'awaitingPrompt'
  | 'error'

// Legal transitions as an adjacency list; a move not listed here is rejected.
const ALLOWED: Record<AgentStatus, readonly AgentStatus[]> = {
  idle: ['running', 'error'],
  running: ['idle', 'awaitingApproval', 'awaitingPrompt', 'error'],
  awaitingApproval: ['running', 'error', 'idle'],
  awaitingPrompt: ['running', 'error', 'idle'],
  error: ['running', 'idle'],
}

// Module-scoped: a single chat session per app, mirroring useAgentClient.
const status = ref<AgentStatus>('idle')

export function useAgentStatus() {
  function canTransitionTo(next: AgentStatus): boolean {
    return ALLOWED[status.value].includes(next)
  }

  function transition(next: AgentStatus): boolean {
    if (status.value === next) return true
    if (!canTransitionTo(next)) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn(`[useAgentStatus] rejected transition ${status.value} → ${next}`)
      }
      return false
    }
    status.value = next
    return true
  }

  /** True while the agent is computing — a new run must no-op. */
  function isBusy(): boolean {
    return status.value === 'running'
  }

  /** True while the agent is blocked on the user (approval or prompt). */
  function isWaitingForUser(): boolean {
    return status.value === 'awaitingApproval' || status.value === 'awaitingPrompt'
  }

  function reset(): void {
    status.value = 'idle'
  }

  return {
    status: readonly(status),
    transition,
    canTransitionTo,
    isBusy,
    isWaitingForUser,
    reset,
  }
}

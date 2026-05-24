/**
 * Pure AG-UI event reducer.
 *
 * Ported line-for-line from the Dart reference at
 * `forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/data/agent_state_reducer.dart`,
 * so semantic drift between the Vue + Svelte + Flutter chat clients is
 * impossible by construction. The Dart side is canonical because it
 * already ships the only full implementation (TOOL_CALL_ARGS handling
 * aside, which is intentionally a no-op pending Pillar G.2).
 *
 * Discipline:
 *
 *   - Pure: `reduce(snapshot, event) -> snapshot`. No I/O, no globals,
 *     no time-of-day. Every call returns a fresh object (immutable
 *     update via spread), so per-framework reactivity wrappers
 *     (Vue `shallowRef`, Svelte `$state`, Flutter `Notifier`) can
 *     reference-compare.
 *   - Defensive: malformed JSON Patch operations in STATE_DELTA are
 *     swallowed — the reducer returns the unchanged snapshot rather
 *     than crashing the stream. Same for out-of-order TEXT_MESSAGE_*:
 *     a CONTENT for an unknown messageId falls back to the last
 *     message in the list (matches the Dart fallback at line 101–102).
 *   - Forward-compat: UnknownEvent + unrecognised CUSTOM names are
 *     silent no-ops so server-side upgrades don't crash old clients.
 */

import { applyPatch, type Operation } from 'fast-json-patch'

import type { AgUiEvent } from './events.js'
import {
  agentStateFromRaw,
  EMPTY_AGENT_STATE,
  type ChatMessage,
  type ChatRole,
  type ChatStateSnapshot,
  type ToolCallInfo,
  type UserPromptPayload,
  type WorkspaceActivity,
} from './snapshot.js'

export function reduce(
  snapshot: ChatStateSnapshot,
  event: AgUiEvent,
): ChatStateSnapshot {
  switch (event.type) {
    case 'RUN_STARTED':
      // New runs start with a clean error slate — a stale error from a
      // prior failed run shouldn't shadow the new one's status banner.
      return { ...snapshot, isRunning: true, error: null }

    case 'RUN_FINISHED':
      return { ...snapshot, isRunning: false }

    case 'RUN_ERROR':
      return { ...snapshot, isRunning: false, error: event.message }

    case 'TEXT_MESSAGE_START': {
      const role = parseRole(event.role)
      const msg: ChatMessage = {
        id: event.messageId,
        role,
        content: '',
        isStreaming: true,
      }
      return { ...snapshot, messages: [...snapshot.messages, msg] }
    }

    case 'TEXT_MESSAGE_CONTENT': {
      // No messages yet → drop the delta. (Servers that emit
      // CONTENT before START are buggy, but we degrade gracefully.)
      if (snapshot.messages.length === 0) return snapshot
      // Find the last message with the matching id; fall back to the
      // very last message. This mirrors Dart's lastIndexWhere +
      // `length - 1` fallback (line 101–102 of the reference).
      const idx = lastIndexOf(snapshot.messages, (m) => m.id === event.messageId)
      const targetIdx = idx >= 0 ? idx : snapshot.messages.length - 1
      const target = snapshot.messages[targetIdx]!
      const updated: ChatMessage = {
        ...target,
        content: target.content + event.delta,
      }
      const messages = snapshot.messages.slice()
      messages[targetIdx] = updated
      return { ...snapshot, messages }
    }

    case 'TEXT_MESSAGE_END': {
      const messages = snapshot.messages.map((m) =>
        m.id === event.messageId ? { ...m, isStreaming: false } : m,
      )
      return { ...snapshot, messages }
    }

    case 'MESSAGES_SNAPSHOT': {
      // Wholesale replace — bypass streaming. Used for backfill / sync.
      const messages: ChatMessage[] = event.messages.map((raw) => ({
        id: String(raw['id'] ?? ''),
        role: parseRole(String(raw['role'] ?? '')),
        content: String(raw['content'] ?? ''),
        isStreaming: false,
      }))
      return { ...snapshot, messages }
    }

    case 'STATE_SNAPSHOT':
      return { ...snapshot, agentState: agentStateFromRaw(event.snapshot) }

    case 'STATE_DELTA': {
      // Apply RFC 6902 patch on a clone of the raw map. fast-json-patch
      // mutates in place when `mutateDocument=true`, so we explicitly
      // clone first to keep the reducer pure.
      const rawClone = structuredClone(snapshot.agentState.raw)
      try {
        const ops = event.delta as unknown as Operation[]
        applyPatch(rawClone, ops, /* validate */ false, /* mutateDocument */ true)
      } catch {
        // Malformed patch → keep old state, wait for the next snapshot.
        // Matches Dart's silent-catch at line 135–137 of the reference.
        return snapshot
      }
      return { ...snapshot, agentState: agentStateFromRaw(rawClone) }
    }

    case 'CUSTOM':
      return reduceCustom(snapshot, event.name, event.value)

    case 'TOOL_CALL_START': {
      const call: ToolCallInfo = {
        id: event.toolCallId,
        name: event.toolCallName,
        status: 'running',
      }
      return { ...snapshot, activeToolCalls: [...snapshot.activeToolCalls, call] }
    }

    case 'TOOL_CALL_ARGS': {
      const activeToolCalls = snapshot.activeToolCalls.map((c) =>
        c.id === event.toolCallId
          ? { ...c, argsBuffer: (c.argsBuffer ?? '') + event.delta }
          : c,
      )
      return { ...snapshot, activeToolCalls }
    }

    case 'TOOL_CALL_END': {
      const activeToolCalls = snapshot.activeToolCalls.map((c) => {
        if (c.id !== event.toolCallId) return c
        const buffer = c.argsBuffer
        if (buffer === undefined || buffer.length === 0) {
          return { ...c, status: 'completed' as const }
        }
        let pretty: string
        try {
          pretty = JSON.stringify(JSON.parse(buffer), null, 2)
        } catch {
          pretty = buffer
        }
        return { ...c, status: 'completed' as const, argsPretty: pretty }
      })
      return { ...snapshot, activeToolCalls }
    }

    case 'ACTIVITY_SNAPSHOT': {
      const engine: WorkspaceActivity['engine'] =
        event.content['engine'] === 'mcp-ext' ? 'mcp-ext' : 'ag-ui'
      const activity: WorkspaceActivity = {
        engine,
        activityType: event.activityType,
        messageId: event.messageId,
        content: event.content,
      }
      if (event.content['target'] === 'canvas') {
        return { ...snapshot, canvasActivity: activity }
      }
      return { ...snapshot, workspaceActivity: activity }
    }

    case 'UNKNOWN':
      // Forward-compat: a parsed-but-unknown event type is a no-op.
      // Consumers can warn elsewhere if they care.
      return snapshot

    /* c8 ignore next 3 — exhaustive switch enforced by `never` */
    default: {
      const _exhaustive: never = event
      void _exhaustive
      return snapshot
    }
  }
}

function reduceCustom(
  snapshot: ChatStateSnapshot,
  name: string,
  value: unknown,
): ChatStateSnapshot {
  switch (name) {
    case 'deepagent.state_snapshot': {
      // The snapshot lives under `value.state` in the deepagent shape.
      const raw =
        typeof value === 'object' && value !== null
          ? ((value as Record<string, unknown>)['state'] ?? value)
          : {}
      if (typeof raw !== 'object' || raw === null) return snapshot
      return { ...snapshot, agentState: agentStateFromRaw(raw as Record<string, unknown>) }
    }
    case 'deepagent.user_prompt': {
      const prompt = parseUserPrompt(value)
      if (!prompt) return snapshot
      return { ...snapshot, pendingPrompt: prompt }
    }
    /* c8 ignore next 2 — silent on unrecognised CUSTOM names */
    default:
      return snapshot
  }
}

function parseUserPrompt(value: unknown): UserPromptPayload | null {
  if (typeof value !== 'object' || value === null) return null
  const v = value as Record<string, unknown>
  const toolCallId = String(v['toolCallId'] ?? '')
  const question = String(v['question'] ?? '')
  if (!toolCallId || !question) return null
  const rawOptions = Array.isArray(v['options']) ? v['options'] : []
  const options = rawOptions
    .filter((o): o is Record<string, unknown> => typeof o === 'object' && o !== null)
    .map((o) => ({
      id: String(o['id'] ?? ''),
      label: String(o['label'] ?? ''),
    }))
    .filter((o) => o.id && o.label)
  return { toolCallId, question, options }
}

/** Resolve the pending prompt by id, clearing it from the snapshot. */
export function clearPendingPromptIfMatches(
  snapshot: ChatStateSnapshot,
  toolCallId: string,
): ChatStateSnapshot {
  if (!snapshot.pendingPrompt || snapshot.pendingPrompt.toolCallId !== toolCallId) {
    return snapshot
  }
  return { ...snapshot, pendingPrompt: null }
}

/** Reset to a brand-new conversation — used when the user starts over. */
export function resetSnapshot(): ChatStateSnapshot {
  return {
    messages: [],
    activeToolCalls: [],
    pendingPrompt: null,
    canvasActivity: null,
    workspaceActivity: null,
    agentState: EMPTY_AGENT_STATE,
    isRunning: false,
    error: null,
  }
}

function parseRole(raw: string): ChatRole {
  if (raw === 'user' || raw === 'system') return raw
  // Defensive default — unknown roles become assistant turns. Mirrors
  // the Dart `chatRoleFromString` fallback.
  return 'assistant'
}

function lastIndexOf<T>(arr: readonly T[], pred: (x: T) => boolean): number {
  for (let i = arr.length - 1; i >= 0; i--) {
    if (pred(arr[i]!)) return i
  }
  return -1
}

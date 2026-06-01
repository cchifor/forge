/**
 * AG-UI event union for the forge canvas runtime.
 *
 * Mirrors the Dart `AgUiEvent` sealed class in
 * `packages/forge-canvas-dart/lib/src/generated/events.dart` line-for-line,
 * so the TS reducer can be ported from
 * `forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/data/agent_state_reducer.dart`
 * without semantic drift.
 *
 * The discriminator is the `type` field on each variant (matching the
 * wire format AG-UI servers emit). Use the {@link parseEvent} helper to
 * decode a raw frame; it returns `UnknownEvent` rather than throwing so
 * forward-compat with future server-side event types is graceful.
 *
 * Custom deepagent events arrive under the umbrella `CUSTOM` type with
 * a `name` field — today only two names are recognised
 * (`deepagent.state_snapshot` and `deepagent.user_prompt`); the reducer
 * silently ignores any other CUSTOM name.
 */

export type AgUiEvent =
  | RunStartedEvent
  | RunFinishedEvent
  | RunErrorEvent
  | TextMessageStartEvent
  | TextMessageContentEvent
  | TextMessageEndEvent
  | MessagesSnapshotEvent
  | StateSnapshotEvent
  | StateDeltaEvent
  | CustomEvent
  | ToolCallStartEvent
  | ToolCallArgsEvent
  | ToolCallEndEvent
  | ActivitySnapshotEvent
  | UnknownEvent

export interface RunStartedEvent {
  type: 'RUN_STARTED'
}

export interface RunFinishedEvent {
  type: 'RUN_FINISHED'
}

export interface RunErrorEvent {
  type: 'RUN_ERROR'
  message: string
}

export interface TextMessageStartEvent {
  type: 'TEXT_MESSAGE_START'
  messageId: string
  role: string
}

export interface TextMessageContentEvent {
  type: 'TEXT_MESSAGE_CONTENT'
  messageId: string
  delta: string
}

export interface TextMessageEndEvent {
  type: 'TEXT_MESSAGE_END'
  messageId: string
}

export interface MessagesSnapshotEvent {
  type: 'MESSAGES_SNAPSHOT'
  messages: Array<Record<string, unknown>>
}

export interface StateSnapshotEvent {
  type: 'STATE_SNAPSHOT'
  snapshot: Record<string, unknown>
}

/** JSON Patch operations (RFC 6902). */
export interface StateDeltaEvent {
  type: 'STATE_DELTA'
  delta: Array<Record<string, unknown>>
}

export interface CustomEvent {
  type: 'CUSTOM'
  name: string
  value: unknown
}

export interface ToolCallStartEvent {
  type: 'TOOL_CALL_START'
  toolCallId: string
  toolCallName: string
}

/**
 * `delta` is the args-streaming chunk. The current reducer ignores this
 * event — kept in the union so the parser doesn't surface it as
 * UnknownEvent (which would noise the logs) and so future "collapsible
 * args preview" work (Pillar G.2 in the architectural plan) can wire
 * straight into the reducer without a parser change.
 */
export interface ToolCallArgsEvent {
  type: 'TOOL_CALL_ARGS'
  toolCallId: string
  delta: string
}

export interface ToolCallEndEvent {
  type: 'TOOL_CALL_END'
  toolCallId: string
}

export interface ActivitySnapshotEvent {
  type: 'ACTIVITY_SNAPSHOT'
  messageId: string
  activityType: string
  content: Record<string, unknown>
}

/**
 * Forward-compat: a parsed but unrecognised event. The reducer no-ops
 * on these; consumers can warn or log if they like.
 */
export interface UnknownEvent {
  type: 'UNKNOWN'
  rawType: string
  raw: Record<string, unknown>
}

const KNOWN_TYPES: ReadonlySet<string> = new Set([
  'RUN_STARTED',
  'RUN_FINISHED',
  'RUN_ERROR',
  'TEXT_MESSAGE_START',
  'TEXT_MESSAGE_CONTENT',
  'TEXT_MESSAGE_END',
  'MESSAGES_SNAPSHOT',
  'STATE_SNAPSHOT',
  'STATE_DELTA',
  'CUSTOM',
  'TOOL_CALL_START',
  'TOOL_CALL_ARGS',
  'TOOL_CALL_END',
  'ACTIVITY_SNAPSHOT',
])

/**
 * Decode a raw AG-UI frame into a typed {@link AgUiEvent}.
 *
 * Defensively coerces missing string fields to `""` and missing
 * structured fields to `[]` / `{}` — matches the Dart parser's
 * fallback discipline so server-side stragglers (e.g. an event that
 * forgot to set `delta: ""`) don't poison the reducer.
 *
 * Returns `UnknownEvent` for any unrecognised `type` instead of
 * throwing — the wire is server-side under upgrade pressure and we'd
 * rather the UI degrade gracefully than crash on a new event variant.
 */
export function parseEvent(frame: Record<string, unknown>): AgUiEvent {
  const rawType = String(frame['type'] ?? '')
  if (!KNOWN_TYPES.has(rawType)) {
    return { type: 'UNKNOWN', rawType, raw: frame }
  }
  switch (rawType) {
    case 'RUN_STARTED':
      return { type: 'RUN_STARTED' }
    case 'RUN_FINISHED':
      return { type: 'RUN_FINISHED' }
    case 'RUN_ERROR':
      return { type: 'RUN_ERROR', message: String(frame['message'] ?? '') }
    case 'TEXT_MESSAGE_START':
      return {
        type: 'TEXT_MESSAGE_START',
        messageId: String(frame['messageId'] ?? ''),
        role: String(frame['role'] ?? 'assistant'),
      }
    case 'TEXT_MESSAGE_CONTENT':
      return {
        type: 'TEXT_MESSAGE_CONTENT',
        messageId: String(frame['messageId'] ?? ''),
        delta: String(frame['delta'] ?? ''),
      }
    case 'TEXT_MESSAGE_END':
      return {
        type: 'TEXT_MESSAGE_END',
        messageId: String(frame['messageId'] ?? ''),
      }
    case 'MESSAGES_SNAPSHOT': {
      const messages = Array.isArray(frame['messages']) ? frame['messages'] : []
      return {
        type: 'MESSAGES_SNAPSHOT',
        messages: messages.filter((m): m is Record<string, unknown> => isPlainObject(m)),
      }
    }
    case 'STATE_SNAPSHOT': {
      const snapshot = isPlainObject(frame['snapshot']) ? frame['snapshot'] : {}
      return { type: 'STATE_SNAPSHOT', snapshot }
    }
    case 'STATE_DELTA': {
      const delta = Array.isArray(frame['delta']) ? frame['delta'] : []
      return {
        type: 'STATE_DELTA',
        delta: delta.filter((op): op is Record<string, unknown> => isPlainObject(op)),
      }
    }
    case 'CUSTOM':
      return {
        type: 'CUSTOM',
        name: String(frame['name'] ?? ''),
        value: frame['value'],
      }
    case 'TOOL_CALL_START':
      return {
        type: 'TOOL_CALL_START',
        toolCallId: String(frame['toolCallId'] ?? ''),
        toolCallName: String(frame['toolCallName'] ?? ''),
      }
    case 'TOOL_CALL_ARGS':
      return {
        type: 'TOOL_CALL_ARGS',
        toolCallId: String(frame['toolCallId'] ?? ''),
        delta: String(frame['delta'] ?? ''),
      }
    case 'TOOL_CALL_END':
      return {
        type: 'TOOL_CALL_END',
        toolCallId: String(frame['toolCallId'] ?? ''),
      }
    case 'ACTIVITY_SNAPSHOT': {
      const content = isPlainObject(frame['content']) ? frame['content'] : {}
      return {
        type: 'ACTIVITY_SNAPSHOT',
        messageId: String(frame['messageId'] ?? ''),
        activityType: String(frame['activityType'] ?? ''),
        content,
      }
    }
    /* c8 ignore next 2 — exhaustive switch over KNOWN_TYPES */
    default:
      return { type: 'UNKNOWN', rawType, raw: frame }
  }
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

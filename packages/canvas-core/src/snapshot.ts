/**
 * Immutable chat-state snapshot consumed by the AG-UI reducer.
 *
 * Mirrors the Dart `ChatStateSnapshot` in
 * `forge/templates/apps/flutter-frontend-template/{{project_slug}}/lib/src/features/chat/data/agent_state_reducer.dart`
 * field-for-field. Per-framework adapters (Vue `shallowRef`,
 * Svelte `$state`, Flutter `Notifier`) wrap this immutable record so
 * the pure reducer stays portable across runtimes.
 */

export type ChatRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  id: string
  role: ChatRole
  content: string
  isStreaming: boolean
}

export type ToolCallStatus = 'running' | 'completed' | 'error'

export interface ToolCallInfo {
  id: string
  name: string
  status: ToolCallStatus
  args?: Record<string, unknown>
  argsBuffer?: string
  argsPretty?: string
}

export interface UserPromptOption {
  // Matches the generated ui-protocol option shape consumed by UserPromptCard
  // (renders ``label`` + ``recommended``); no synthetic ``id``.
  label: string
  description?: string
  recommended?: string
}

export interface UserPromptPayload {
  // snake_case to match the generated ui-protocol UserPromptPayload (the wire
  // format) consumed by UserPromptCard — see events.gen.ts / the schema.
  tool_call_id: string
  question: string
  options: UserPromptOption[]
}

/** Free-form workspace activity routed by `content.target` / `engine`. */
export interface WorkspaceActivity {
  engine: 'ag-ui' | 'mcp-ext'
  activityType: string
  messageId: string
  content: Record<string, unknown>
}

/**
 * Deepagent-flavoured agent state. The raw map is the source of truth
 * for JSON Patch (STATE_DELTA); derived fields are convenience views.
 * Adapters that only care about raw can ignore the derived ones.
 */
export interface AgentState {
  cost: Record<string, unknown> | null
  context: Record<string, unknown> | null
  todos: Array<Record<string, unknown>>
  files: string[]
  uploads: Array<Record<string, unknown>>
  model: string | null
  raw: Record<string, unknown>
}

export const EMPTY_AGENT_STATE: AgentState = {
  cost: null,
  context: null,
  todos: [],
  files: [],
  uploads: [],
  model: null,
  raw: {},
}

export interface ChatStateSnapshot {
  messages: ChatMessage[]
  activeToolCalls: ToolCallInfo[]
  pendingPrompt: UserPromptPayload | null
  canvasActivity: WorkspaceActivity | null
  workspaceActivity: WorkspaceActivity | null
  agentState: AgentState
  isRunning: boolean
  error: string | null
}

/** A snapshot fresh out of the box — same defaults as Dart's `ChatStateSnapshot()`. */
export const EMPTY_CHAT_SNAPSHOT: ChatStateSnapshot = {
  messages: [],
  activeToolCalls: [],
  pendingPrompt: null,
  canvasActivity: null,
  workspaceActivity: null,
  agentState: EMPTY_AGENT_STATE,
  isRunning: false,
  error: null,
}

/**
 * Derive an {@link AgentState} from a raw deepagent map.
 *
 * Defensive on every field — a deepagent build that's behind on the
 * schema (or a malformed STATE_SNAPSHOT) shouldn't crash the reducer.
 * Unknown fields are dropped silently; unrecognised types fall back to
 * empty defaults.
 */
export function agentStateFromRaw(raw: Record<string, unknown>): AgentState {
  return {
    cost: pickObject(raw['cost']),
    context: pickObject(raw['context']),
    todos: pickArrayOfObjects(raw['todos']),
    files: pickArrayOfStrings(raw['files']),
    uploads: pickArrayOfObjects(raw['uploads']),
    model: typeof raw['model'] === 'string' ? raw['model'] : null,
    raw,
  }
}

function pickObject(v: unknown): Record<string, unknown> | null {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null
}

function pickArrayOfObjects(v: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(v)) return []
  return v.filter(
    (x): x is Record<string, unknown> =>
      typeof x === 'object' && x !== null && !Array.isArray(x),
  )
}

function pickArrayOfStrings(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v.filter((x): x is string => typeof x === 'string')
}

import type { Message } from '@ag-ui/core'
import { EventType } from '@ag-ui/core'

// Theme 2B — payload + event-union types come from the generated
// ``events.gen.ts`` so adding a new ui-protocol schema automatically
// extends this surface and the exhaustiveness check in
// :func:`assertUnreachable` forces every consumer to handle it.
export type {
  AgentState,
  WorkspaceActivity,
  UserPromptPayload,
  HitlResponse,
  AgUiPayload,
  McpExtPayload,
  AgUiEvent,
  AgUiEventKind,
} from './events.gen'
export { assertUnreachable, getEventKind } from './events.gen'

import type {
  AgentState as _AgentState,
  ToolCallInfo as _WireToolCallInfo,
} from './events.gen'

export type DeepAgentCustomPayload = _AgentState

/**
 * Client-side tool-call record.
 *
 * Extends the wire-protocol :class:`ToolCallInfo` (generated from
 * ``tool_call_info.schema.json``) with two client-only fields:
 *
 * - ``argsBuffer`` — raw delta accumulator. Appended on every
 *   ``TOOL_CALL_ARGS`` event so the UI can show the partial-JSON
 *   stream live (newline-stripped) before the call completes.
 * - ``argsPretty`` — set on ``TOOL_CALL_END``. Pretty-printed
 *   ``JSON.stringify(JSON.parse(argsBuffer), null, 2)`` on success;
 *   falls back to the raw buffer when the model emits non-JSON.
 *
 * Field names mirror Svelte's ``ToolCallInfo`` + Flutter's
 * :class:`ToolCallInfo` so the contract test at
 * ``tests/test_chat_tool_call_args_contract.py`` finds a consistent
 * surface across all three stacks.
 */
export interface ToolCallInfo extends _WireToolCallInfo {
  /** Raw delta accumulator — appended on every TOOL_CALL_ARGS event. */
  argsBuffer?: string
  /** Pretty-printed JSON set on TOOL_CALL_END; falls back to raw on parse error. */
  argsPretty?: string
}

export type WorkspaceAction = { type: string; toolCallId?: string; data: Record<string, any> }

// ── HITL (Human-in-the-Loop) ──
// ``UserPromptOption`` is the element type of ``UserPromptPayload.options``;
// keep it exported so existing consumers (forms, prompts) compile.
export interface UserPromptOption {
  label: string
  description?: string
  recommended?: string
}

export type { Message }
export { EventType }

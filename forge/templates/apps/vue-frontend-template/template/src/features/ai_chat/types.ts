import type { Message } from '@ag-ui/core'
import { EventType } from '@ag-ui/core'

// Theme 2B — payload + event-union types come from the generated
// ``events.gen.ts`` so adding a new ui-protocol schema automatically
// extends this surface and the exhaustiveness check in
// :func:`assertUnreachable` forces every consumer to handle it.
export type {
  AgentState,
  WorkspaceActivity,
  ToolCallInfo,
  UserPromptPayload,
  HitlResponse,
  AgUiPayload,
  McpExtPayload,
  AgUiEvent,
  AgUiEventKind,
} from './events.gen'
export { assertUnreachable, getEventKind } from './events.gen'

import type { AgentState as _AgentState } from './events.gen'

export type DeepAgentCustomPayload = _AgentState

export type WorkspaceAction = { type: string; data: Record<string, any> }

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

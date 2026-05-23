import type { Message } from '@ag-ui/core';
import { EventType } from '@ag-ui/core';

export interface AgentState {
	todos?: Array<{ content: string; status: string }>;
	files?: string[];
	uploads?: Array<{ name: string; path: string; size: number }>;
	cost?: {
		total_usd: number;
		total_tokens: number;
		run_usd: number;
		run_tokens: number;
	};
	context?: {
		usage_pct: number;
		current_tokens: number;
		max_tokens: number;
	};
	model?: string;
	[key: string]: unknown;
}

export type DeepAgentCustomPayload = AgentState;

export type WorkspaceAction = { type: string; data: Record<string, unknown> };

export interface WorkspaceActivity {
	engine: 'ag-ui' | 'mcp-ext';
	activityType: string;
	messageId: string;
	content: Record<string, unknown>;
}

// ── Tool call tracking ──

/**
 * Client-side tool-call record.
 *
 * The wire shape (``id``/``name``/``status``/``args``) mirrors the
 * UI-protocol :class:`ToolCallInfo` schema. The two trailing fields
 * are client-only state for Pillar G.2 args-streaming:
 *
 * - ``argsBuffer`` — raw delta accumulator. Every ``TOOL_CALL_ARGS``
 *   event appends ``event.delta`` so the UI can show the partial JSON
 *   live (newlines stripped) before the (potentially slow) tool
 *   returns.
 * - ``argsPretty`` — set on ``TOOL_CALL_END``. Pretty-printed
 *   ``JSON.stringify(JSON.parse(argsBuffer), null, 2)`` on success;
 *   falls back to the raw buffer on parse error so the user always
 *   sees *something* for debugging.
 *
 * Field names mirror Vue's ``ToolCallInfo`` + Flutter's
 * :class:`ToolCallInfo` so the contract test at
 * ``tests/test_chat_tool_call_args_contract.py`` finds a consistent
 * surface across all three stacks.
 */
export interface ToolCallInfo {
	id: string;
	name: string;
	status: 'running' | 'completed' | 'error';
	args?: Record<string, unknown>;
	/** Raw delta accumulator — appended on every TOOL_CALL_ARGS event. */
	argsBuffer?: string;
	/** Pretty-printed JSON set on TOOL_CALL_END; falls back to raw on parse error. */
	argsPretty?: string;
}

// ── HITL (Human-in-the-Loop) ──

export interface UserPromptOption {
	label: string;
	description?: string;
	recommended?: string;
}

export interface UserPromptPayload {
	tool_call_id: string;
	question: string;
	options: UserPromptOption[];
}

export interface HitlResponse {
	tool_call_id: string;
	answer: string;
}

export type ChatRunOptions = {
	model?: string;
	approval?: string;
	hitlResponse?: HitlResponse;
	/**
	 * IDs returned by ``POST /api/v1/chat-files`` for the user's next turn.
	 * Forwarded to the agent as ``attachment_ids`` in ``forwardedProps`` —
	 * the agent then resolves each ID via ``GET /api/v1/chat-files/{id}``
	 * to read the uploaded bytes. Chips for these are owned by
	 * ``AiChatInput.svelte`` and cleared after a successful send.
	 */
	attachmentIds?: string[];
};

/**
 * A file the user has uploaded but not yet sent — rendered as a chip
 * above the textarea, removable, and forwarded into ``ChatRunOptions``
 * on the next send.
 */
export interface ChatAttachment {
	id: string;
	filename: string;
	mime_type?: string;
	size_bytes?: number;
}

export type { Message };
export { EventType };

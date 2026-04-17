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

export interface ToolCallInfo {
	id: string;
	name: string;
	status: 'running' | 'completed' | 'error';
	args?: Record<string, unknown>;
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
};

export type { Message };
export { EventType };

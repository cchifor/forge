import { HttpAgent } from '@ag-ui/client';
import type { CustomEvent as AgUiCustomEvent, Message, RunErrorEvent } from '@ag-ui/core';
import { applyPatch } from 'fast-json-patch';

import type {
	AgentState,
	ChatRunOptions,
	DeepAgentCustomPayload,
	HitlResponse,
	ToolCallInfo,
	UserPromptPayload,
	WorkspaceActivity
} from '../chat.types';
import { getOptionalAuthToken } from './auth-shim.svelte';

// Module-scoped reactive state — single chat thread per app session.
let messages = $state<Message[]>([]);
let agentState = $state<AgentState>({});
let customState = $state<DeepAgentCustomPayload>({});
let pendingPrompt = $state<UserPromptPayload | null>(null);
let canvasActivity = $state<WorkspaceActivity | null>(null);
let workspaceActivity = $state<WorkspaceActivity | null>(null);
let activeToolCalls = $state<ToolCallInfo[]>([]);
let isRunning = $state(false);
let lastError = $state<Error | null>(null);
let currentThreadId = crypto.randomUUID();

let agent: HttpAgent | null = null;

function getAgent(): HttpAgent {
	if (!agent) {
		const url =
			(import.meta.env.VITE_AGENT_BASE_URL as string | undefined) ||
			`${window.location.origin}/agent/`;
		agent = new HttpAgent({ url });
	}
	return agent;
}

function resetTransientState() {
	agentState = {};
	customState = {};
	pendingPrompt = null;
	canvasActivity = null;
	workspaceActivity = null;
	activeToolCalls = [];
	lastError = null;
}

async function runAgent(options?: ChatRunOptions) {
	const a = getAgent();

	// Forward Bearer token so the agent service trusts the caller (Gatekeeper-issued).
	// Soft-imports auth so the chat compiles in `include_auth=false` projects too.
	const token = await getOptionalAuthToken();
	if (token) {
		a.headers = { Authorization: `Bearer ${token}` };
	}

	a.setMessages([...messages]);
	a.setState({ ...agentState });

	isRunning = true;
	lastError = null;

	const { hitlResponse, ...rest } = options ?? {};
	const forwardedProps: Record<string, unknown> = { ...rest };
	if (hitlResponse) {
		forwardedProps.hitl_response = hitlResponse;
	}

	try {
		await a.runAgent(
			{
				threadId: currentThreadId,
				runId: crypto.randomUUID(),
				tools: [],
				context: [],
				forwardedProps
			},
			{
				onRunStartedEvent: async () => {
					isRunning = true;
				},

				onRunFinishedEvent: async () => {
					isRunning = false;
				},

				onRunErrorEvent: async ({ event }: { event: RunErrorEvent }) => {
					lastError = new Error(event.message || 'Agent run failed');
					isRunning = false;
				},

				onTextMessageStartEvent: async ({ event }) => {
					messages = [
						...messages,
						{ id: event.messageId, role: event.role || 'assistant', content: '' }
					];
				},

				onTextMessageContentEvent: async ({ event }) => {
					if (messages.length === 0) return;
					const last = messages[messages.length - 1];
					messages = [
						...messages.slice(0, -1),
						{ ...last, content: (last.content || '') + event.delta }
					];
				},

				onMessagesSnapshotEvent: async ({ event }) => {
					messages = event.messages ?? [];
				},

				onStateSnapshotEvent: async ({ event }) => {
					const snapshot = (event.snapshot ?? {}) as AgentState;
					agentState = snapshot;
					customState = snapshot as DeepAgentCustomPayload;
				},

				onCustomEvent: async ({ event }: { event: AgUiCustomEvent }) => {
					if (event.name === 'deepagent.state_snapshot') {
						customState = event.value as DeepAgentCustomPayload;
					} else if (event.name === 'deepagent.user_prompt') {
						pendingPrompt = event.value as UserPromptPayload;
					}
				},

				onStateDeltaEvent: async ({ event }) => {
					try {
						const patched = applyPatch({ ...customState }, event.delta, true, false);
						customState = patched.newDocument as DeepAgentCustomPayload;
					} catch {
						// Delta failed — wait for the next snapshot.
					}
				},

				onActivitySnapshotEvent: async ({ event }) => {
					const content = (event.content ?? {}) as Record<string, unknown>;
					const activity: WorkspaceActivity = {
						engine: (content.engine as 'ag-ui' | 'mcp-ext') || 'ag-ui',
						activityType: event.activityType,
						messageId: event.messageId,
						content
					};
					if (content.target === 'canvas') {
						canvasActivity = activity;
					} else {
						workspaceActivity = activity;
					}
				},

				onToolCallStartEvent: async ({ event }) => {
					activeToolCalls = [
						...activeToolCalls,
						{ id: event.toolCallId, name: event.toolCallName, status: 'running' }
					];
				},

				onToolCallEndEvent: async ({ event }) => {
					activeToolCalls = activeToolCalls.map((tc) =>
						tc.id === event.toolCallId ? { ...tc, status: 'completed' } : tc
					);
				}
			}
		);
	} catch (e) {
		lastError = e instanceof Error ? e : new Error(String(e));
		isRunning = false;
	}
}

function addUserMessage(content: string) {
	messages = [
		...messages,
		{ id: crypto.randomUUID(), role: 'user', content }
	];
}

function respondToPrompt(answer: string) {
	if (!pendingPrompt) return;
	const hitlResponse: HitlResponse = {
		tool_call_id: pendingPrompt.tool_call_id,
		answer
	};
	addUserMessage(answer);
	pendingPrompt = null;
	void runAgent({ hitlResponse });
}

function editAndResend(messageId: string, newContent: string, options?: ChatRunOptions) {
	const idx = messages.findIndex((m) => m.id === messageId);
	if (idx === -1) return;
	messages = messages.slice(0, idx);
	currentThreadId = crypto.randomUUID();
	resetTransientState();
	addUserMessage(newContent);
	void runAgent(options);
}

function resetThread() {
	currentThreadId = crypto.randomUUID();
	messages = [];
	resetTransientState();
}

function setCanvasActivity(activity: WorkspaceActivity) {
	canvasActivity = activity;
}

function clearCanvas() {
	canvasActivity = null;
}

function clearWorkspaceActivity() {
	workspaceActivity = null;
}

/**
 * Stable AG-UI chat client.
 *
 * Use exactly like `getChatStore()` in components: `const chat = getAgentClient()`
 * exposes reactive getters for state + plain functions for actions. Module-scoped
 * `$state` keeps the thread alive across navigations without prop-drilling.
 */
export function getAgentClient() {
	return {
		get messages() {
			return messages;
		},
		get state() {
			return agentState;
		},
		get customState() {
			return customState;
		},
		get pendingPrompt() {
			return pendingPrompt;
		},
		get canvasActivity() {
			return canvasActivity;
		},
		get workspaceActivity() {
			return workspaceActivity;
		},
		get activeToolCalls() {
			return activeToolCalls;
		},
		get isRunning() {
			return isRunning;
		},
		get error() {
			return lastError;
		},
		runAgent,
		addUserMessage,
		respondToPrompt,
		setCanvasActivity,
		clearCanvas,
		clearWorkspaceActivity,
		editAndResend,
		resetThread
	};
}

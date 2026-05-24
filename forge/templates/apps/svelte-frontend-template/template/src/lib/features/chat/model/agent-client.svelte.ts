import {
	AgUiClient,
	parseEvent,
	reduce,
	resetSnapshot,
	clearPendingPromptIfMatches,
	type AgUiRunPayload,
	type ChatStateSnapshot
} from '@forge/canvas-core';

import type { ChatRunOptions, HitlResponse, WorkspaceActivity } from '../chat.types';
import { getOptionalAuthToken } from './auth-shim.svelte';

// Module-scoped reactive state — single chat thread per app session.
let snapshot = $state<ChatStateSnapshot>(resetSnapshot());
let currentThreadId = crypto.randomUUID();

let lastRunOptions: ChatRunOptions | undefined = undefined;
let hasRun = false;

async function runAgent(options?: ChatRunOptions) {
	lastRunOptions = options;
	hasRun = true;

	const token = await getOptionalAuthToken();
	const headers: Record<string, string> = {};
	if (token) {
		headers['Authorization'] = `Bearer ${token}`;
	}

	// Optimistically mark running + clear stale error.
	snapshot = { ...snapshot, isRunning: true, error: null };

	const { hitlResponse, attachmentIds, ...rest } = options ?? {};
	const forwardedProps: Record<string, unknown> = { ...rest };
	if (hitlResponse) {
		forwardedProps.hitl_response = hitlResponse;
	}
	if (attachmentIds && attachmentIds.length > 0) {
		forwardedProps.attachment_ids = attachmentIds;
	}

	const payload: AgUiRunPayload = {
		threadId: currentThreadId,
		runId: crypto.randomUUID(),
		messages: snapshot.messages.map((m) => ({
			id: m.id,
			role: m.role,
			content: m.content
		})),
		state: snapshot.agentState.raw,
		tools: [],
		context: [],
		forwardedProps
	};

	const url =
		(import.meta.env.VITE_AGENT_BASE_URL as string | undefined) ||
		`${window.location.origin}/agent/`;

	const client = new AgUiClient({
		url,
		parser: (frame) => parseEvent(frame),
		onEvent: (event) => {
			snapshot = reduce(snapshot, event);
		},
		headers
	});

	try {
		await client.runAgent(payload);
		// Server closed cleanly; force-stop if reducer didn't see RUN_FINISHED.
		snapshot = { ...snapshot, isRunning: false };
	} catch (e) {
		snapshot = {
			...snapshot,
			isRunning: false,
			error: e instanceof Error ? e.message : String(e)
		};
	}
}

function addUserMessage(content: string) {
	snapshot = {
		...snapshot,
		messages: [
			...snapshot.messages,
			{ id: crypto.randomUUID(), role: 'user', content, isStreaming: false }
		]
	};
}

function respondToPrompt(answer: string) {
	if (!snapshot.pendingPrompt) return;
	const hitlResponse: HitlResponse = {
		tool_call_id: snapshot.pendingPrompt.toolCallId,
		answer
	};
	snapshot = clearPendingPromptIfMatches(snapshot, snapshot.pendingPrompt.toolCallId);
	addUserMessage(answer);
	void runAgent({ hitlResponse });
}

function editAndResend(messageId: string, newContent: string, options?: ChatRunOptions) {
	const idx = snapshot.messages.findIndex((m) => m.id === messageId);
	if (idx === -1) return;
	const kept = snapshot.messages.slice(0, idx);
	currentThreadId = crypto.randomUUID();
	snapshot = { ...resetSnapshot(), messages: kept };
	addUserMessage(newContent);
	void runAgent(options);
}

function resetThread() {
	currentThreadId = crypto.randomUUID();
	snapshot = resetSnapshot();
	lastRunOptions = undefined;
	hasRun = false;
}

function retryLastRun() {
	if (!hasRun || snapshot.isRunning) return;
	snapshot = { ...snapshot, error: null };
	void runAgent(lastRunOptions);
}

function setCanvasActivity(activity: WorkspaceActivity) {
	snapshot = { ...snapshot, canvasActivity: activity };
}

function clearCanvas() {
	snapshot = { ...snapshot, canvasActivity: null };
}

function clearWorkspaceActivity() {
	snapshot = { ...snapshot, workspaceActivity: null };
}

function dismissError() {
	snapshot = { ...snapshot, error: null };
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
			return snapshot.messages;
		},
		get state() {
			return snapshot.agentState.raw;
		},
		get customState() {
			return snapshot.agentState.raw;
		},
		get pendingPrompt() {
			return snapshot.pendingPrompt;
		},
		get canvasActivity() {
			return snapshot.canvasActivity;
		},
		get workspaceActivity() {
			return snapshot.workspaceActivity;
		},
		get activeToolCalls() {
			return snapshot.activeToolCalls;
		},
		get isRunning() {
			return snapshot.isRunning;
		},
		get error() {
			return snapshot.error ? new Error(snapshot.error) : null;
		},
		runAgent,
		retryLastRun,
		dismissError,
		addUserMessage,
		respondToPrompt,
		setCanvasActivity,
		clearCanvas,
		clearWorkspaceActivity,
		editAndResend,
		resetThread
	};
}

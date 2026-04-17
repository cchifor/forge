import {
	APPROVAL_MODES,
	AVAILABLE_MODELS,
	DEFAULT_APPROVAL,
	DEFAULT_MODEL,
	type ApprovalMode,
	type ModelId
} from '../chat.constants';
import { getAgentClient } from './agent-client.svelte';

const STORAGE_KEY_MODEL = 'chat:model';
const STORAGE_KEY_APPROVAL = 'chat:approval';

function loadStored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
	if (typeof window === 'undefined') return fallback;
	const v = window.localStorage.getItem(key);
	return (allowed as readonly string[]).includes(v ?? '') ? (v as T) : fallback;
}

let model = $state<ModelId>(
	loadStored(STORAGE_KEY_MODEL, DEFAULT_MODEL, AVAILABLE_MODELS.map((m) => m.id))
);
let approvalMode = $state<ApprovalMode>(
	loadStored(STORAGE_KEY_APPROVAL, DEFAULT_APPROVAL, APPROVAL_MODES.map((m) => m.id))
);
let contextLabel = $state('General');

export interface ChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string;
}

/**
 * High-level chat store. Wraps the AG-UI agent client and adds session-level
 * concerns (selected model, approval mode, contextual label). The actual
 * messages, tool calls, and agent state live on the agent client itself —
 * this store reads them through reactive getters.
 */
export function getChatStore() {
	const agent = getAgentClient();

	function sendUserMessage(content: string) {
		const trimmed = content.trim();
		if (!trimmed) return;
		agent.addUserMessage(trimmed);
		void agent.runAgent({ model, approval: approvalMode });
	}

	function setModel(next: ModelId) {
		model = next;
		if (typeof window !== 'undefined') {
			window.localStorage.setItem(STORAGE_KEY_MODEL, next);
		}
	}

	function setApprovalMode(next: ApprovalMode) {
		approvalMode = next;
		if (typeof window !== 'undefined') {
			window.localStorage.setItem(STORAGE_KEY_APPROVAL, next);
		}
	}

	function setContext(label: string) {
		contextLabel = label;
	}

	return {
		// Reactive getters proxy the agent client.
		get messages() {
			return agent.messages;
		},
		get isGenerating() {
			return agent.isRunning;
		},
		get error() {
			return agent.error;
		},
		get activeToolCalls() {
			return agent.activeToolCalls;
		},
		get pendingPrompt() {
			return agent.pendingPrompt;
		},
		get customState() {
			return agent.customState;
		},
		get canvasActivity() {
			return agent.canvasActivity;
		},
		get workspaceActivity() {
			return agent.workspaceActivity;
		},
		// Local session preferences.
		get model() {
			return model;
		},
		get approvalMode() {
			return approvalMode;
		},
		get contextLabel() {
			return contextLabel;
		},
		// Actions.
		addUserMessage: sendUserMessage,
		respondToPrompt: agent.respondToPrompt,
		editAndResend: agent.editAndResend,
		setModel,
		setApprovalMode,
		setContext,
		clearMessages: agent.resetThread,
		clearCanvas: agent.clearCanvas,
		clearWorkspaceActivity: agent.clearWorkspaceActivity
	};
}

// Public surface of the chat feature.
// Components and stores are deliberately re-exported from a single barrel so
// other features (shell, layout, header) stay decoupled from internal layout.

export { getChatStore, type ChatMessage } from './model/chat.svelte';
export { getAgentClient } from './model/agent-client.svelte';
export type {
	AgentState,
	ChatRunOptions,
	HitlResponse,
	Message,
	ToolCallInfo,
	UserPromptOption,
	UserPromptPayload,
	WorkspaceActivity
} from './chat.types';
export {
	APPROVAL_MODES,
	AVAILABLE_MODELS,
	DEFAULT_APPROVAL,
	DEFAULT_MODEL
} from './chat.constants';
export type { ApprovalMode, ModelId } from './chat.constants';

export { default as AgentStatusBar } from './ui/AgentStatusBar.svelte';
export { default as AiChat } from './ui/AiChat.svelte';
export { default as AiChatButton } from './ui/AiChatButton.svelte';
export { default as AiChatInput } from './ui/AiChatInput.svelte';
export { default as AiChatMessage } from './ui/AiChatMessage.svelte';
export { default as ToolCallStatus } from './ui/ToolCallStatus.svelte';
export { default as UserPromptCard } from './ui/UserPromptCard.svelte';

// Workspace pane (file explorer, credentials, approvals, prompts).
export { default as WorkspacePane } from './workspace/WorkspacePane.svelte';
export {
	registerWorkspaceComponent,
	resolveWorkspaceComponent
} from './workspace/registry';
export { AgUiEngine, McpExtEngine } from './workspace/engines';

// Canvas pane (dynamic form, data table, report, code, workflow).
export { default as CanvasPane } from './canvas/CanvasPane.svelte';
export {
	registerCanvasComponent,
	resolveCanvasComponent
} from './canvas/registry';

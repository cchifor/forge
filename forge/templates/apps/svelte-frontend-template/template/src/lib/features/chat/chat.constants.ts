/** Available LLM models the user can pick from in the chat panel header. */
export const AVAILABLE_MODELS = [
	{ id: 'gpt-4.1', label: 'GPT-4.1' },
	{ id: 'gpt-4.1-mini', label: 'GPT-4.1 Mini' },
	{ id: 'claude-sonnet-4', label: 'Claude Sonnet 4' }
] as const;

export type ModelId = (typeof AVAILABLE_MODELS)[number]['id'];

/** Approval modes — `default` = ask before running tools, `bypass` = auto-approve. */
export const APPROVAL_MODES = [
	{ id: 'default', label: 'Default' },
	{ id: 'bypass', label: 'Bypass' }
] as const;

export type ApprovalMode = (typeof APPROVAL_MODES)[number]['id'];

export const DEFAULT_MODEL: ModelId = 'claude-sonnet-4';
export const DEFAULT_APPROVAL: ApprovalMode = 'default';

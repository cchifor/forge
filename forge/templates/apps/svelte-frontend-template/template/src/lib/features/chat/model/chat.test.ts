import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('crypto', {
	randomUUID: () => 'test-uuid-' + Math.random().toString(36).slice(2)
});

// Stub the AG-UI HttpAgent so the test never makes a real HTTP request.
const runAgent = vi.fn().mockResolvedValue(undefined);
vi.mock('@ag-ui/client', () => ({
	HttpAgent: class {
		headers: Record<string, string> = {};
		setMessages = vi.fn();
		setState = vi.fn();
		runAgent = runAgent;
	}
}));

// Auth is a soft dep — return no token so the chat works in any auth mode.
vi.mock('$lib/core/auth/auth.svelte', () => ({
	getAuth: () => ({ getToken: async () => null })
}));

const { getChatStore } = await import('$lib/features/chat/model/chat.svelte');

describe('getChatStore (AG-UI agent client)', () => {
	let store: ReturnType<typeof getChatStore>;

	beforeEach(() => {
		store = getChatStore();
		store.clearMessages();
		runAgent.mockClear();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('exposes the documented surface', () => {
		expect(store).toBeDefined();
		expect(store).toHaveProperty('messages');
		expect(store).toHaveProperty('isGenerating');
		expect(store).toHaveProperty('contextLabel');
		expect(store).toHaveProperty('model');
		expect(store).toHaveProperty('approvalMode');
		expect(store).toHaveProperty('activeToolCalls');
		expect(store).toHaveProperty('pendingPrompt');
		expect(typeof store.addUserMessage).toBe('function');
		expect(typeof store.respondToPrompt).toBe('function');
		expect(typeof store.setModel).toBe('function');
		expect(typeof store.setApprovalMode).toBe('function');
		expect(typeof store.setContext).toBe('function');
		expect(typeof store.clearMessages).toBe('function');
	});

	it('starts with empty messages and isGenerating=false', () => {
		expect(store.messages).toEqual([]);
		expect(store.isGenerating).toBe(false);
	});

	it('addUserMessage appends a user message and triggers an agent run', () => {
		store.addUserMessage('Hello');
		expect(store.messages).toHaveLength(1);
		expect(store.messages[0].role).toBe('user');
		expect(store.messages[0].content).toBe('Hello');
		expect(runAgent).toHaveBeenCalledTimes(1);
	});

	it('ignores empty/whitespace-only input', () => {
		store.addUserMessage('   ');
		expect(store.messages).toHaveLength(0);
		expect(runAgent).not.toHaveBeenCalled();
	});

	it('clearMessages resets the thread', () => {
		store.addUserMessage('Hi');
		expect(store.messages.length).toBeGreaterThan(0);
		store.clearMessages();
		expect(store.messages).toEqual([]);
	});

	it('setContext updates the contextLabel', () => {
		store.setContext('Dashboard');
		expect(store.contextLabel).toBe('Dashboard');
	});

	it('setModel updates the selected model', () => {
		store.setModel('gpt-4.1');
		expect(store.model).toBe('gpt-4.1');
	});

	it('setApprovalMode updates the approval mode', () => {
		store.setApprovalMode('bypass');
		expect(store.approvalMode).toBe('bypass');
	});
});

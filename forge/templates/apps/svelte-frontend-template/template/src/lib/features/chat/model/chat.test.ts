import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('crypto', {
	randomUUID: () => 'test-uuid-' + Math.random().toString(36).slice(2)
});

// Stub the canvas-core AgUiClient so the test never makes a real HTTP request.
const mockRunAgent = vi.fn().mockResolvedValue(undefined);
vi.mock('@forge/canvas-core', async () => {
	const actual = await vi.importActual('@forge/canvas-core');
	return {
		...actual,
		AgUiClient: vi.fn().mockImplementation(() => ({
			runAgent: mockRunAgent
		}))
	};
});

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
		mockRunAgent.mockClear();
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
		expect(typeof store.retryLastRun).toBe('function');
		expect(typeof store.dismissError).toBe('function');
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
		expect(mockRunAgent).toHaveBeenCalledTimes(1);
	});

	it('ignores empty/whitespace-only input', () => {
		store.addUserMessage('   ');
		expect(store.messages).toHaveLength(0);
		expect(mockRunAgent).not.toHaveBeenCalled();
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

	it('retryLastRun re-invokes runAgent with the last forwardedProps', async () => {
		store.setModel('gpt-4.1');
		store.setApprovalMode('bypass');
		store.addUserMessage('Hello');
		expect(mockRunAgent).toHaveBeenCalledTimes(1);
		const firstThreadId = mockRunAgent.mock.calls[0][0].threadId;
		const firstProps = mockRunAgent.mock.calls[0][0].forwardedProps;

		store.retryLastRun();
		// retryLastRun fires a fresh runAgent invocation
		expect(mockRunAgent).toHaveBeenCalledTimes(2);

		// Thread ID is preserved — retry MUST stay on the same conversation.
		const retryThreadId = mockRunAgent.mock.calls[1][0].threadId;
		expect(retryThreadId).toBe(firstThreadId);

		// forwardedProps shape is identical (model + approval).
		const retryProps = mockRunAgent.mock.calls[1][0].forwardedProps;
		expect(retryProps).toEqual(firstProps);
	});

	it('retryLastRun is a no-op before any runAgent call', () => {
		store.retryLastRun();
		expect(mockRunAgent).not.toHaveBeenCalled();
	});

	it('retryLastRun is a no-op while a run is in flight (anti-double-retry)', async () => {
		let resolveRun: (() => void) | null = null;
		mockRunAgent.mockImplementation(
			() => new Promise<void>((resolve) => { resolveRun = resolve }),
		);
		store.addUserMessage('Hello');
		await Promise.resolve();  // let isRunning flip
		expect(mockRunAgent).toHaveBeenCalledTimes(1);
		store.retryLastRun();
		store.retryLastRun();
		store.retryLastRun();
		expect(mockRunAgent).toHaveBeenCalledTimes(1);  // still 1
		resolveRun?.();
	});

	it('dismissError clears the error without re-running', () => {
		expect(() => store.dismissError()).not.toThrow();
		expect(store.error).toBeNull();
	});

	// ── regenerate (G.3) ──

	it('exposes regenerate(messageId: string)', () => {
		expect(typeof store.regenerate).toBe('function');
		expect(store.regenerate.length).toBe(1);
	});

	// Helper: drive an assistant reply through the AG-UI event subscriber
	// so we get a real assistant message without mutating module state.
	async function seedAssistantReply(asstId: string, asstContent: string) {
		mockRunAgent.mockImplementationOnce(async (_p: unknown, sub: any) => {
			await sub.onTextMessageStartEvent({
				event: { messageId: asstId, role: 'assistant' }
			});
			await sub.onTextMessageContentEvent({ event: { delta: asstContent } });
			await sub.onRunFinishedEvent({ event: {} });
		});
		store.addUserMessage('hi');
		// Wait for the addUserMessage-triggered runAgent to complete.
		await Promise.resolve();
		await Promise.resolve();
	}

	it('regenerate truncates from messageId and preserves threadId', async () => {
		store.setModel('gpt-4.1');
		store.setApprovalMode('bypass');
		await seedAssistantReply('asst-1', 'first reply');
		expect(store.messages).toHaveLength(2);
		const firstThreadId = mockRunAgent.mock.calls[0][0].threadId;

		mockRunAgent.mockResolvedValueOnce(undefined);
		store.regenerate('asst-1');
		await Promise.resolve();

		expect(store.messages).toHaveLength(1);
		expect(store.messages[0].role).toBe('user');
		expect(mockRunAgent).toHaveBeenCalledTimes(2);
		// ── Load-bearing: regenerate keeps the thread. ──
		expect(mockRunAgent.mock.calls[1][0].threadId).toBe(firstThreadId);
	});

	it('regenerate re-uses lastRunOptions (model + approval)', async () => {
		store.setModel('gpt-4.1');
		store.setApprovalMode('bypass');
		await seedAssistantReply('asst-2', 'reply');
		const firstProps = mockRunAgent.mock.calls[0][0].forwardedProps;

		mockRunAgent.mockResolvedValueOnce(undefined);
		store.regenerate('asst-2');
		await Promise.resolve();

		expect(mockRunAgent.mock.calls[1][0].forwardedProps).toEqual(firstProps);
	});

	it('regenerate is a no-op for unknown messageId', async () => {
		await seedAssistantReply('asst-3', 'reply');
		expect(mockRunAgent).toHaveBeenCalledTimes(1);

		store.regenerate('does-not-exist');
		await Promise.resolve();

		expect(mockRunAgent).toHaveBeenCalledTimes(1);
		expect(store.messages).toHaveLength(2);
	});

	it('regenerate is a no-op while a run is in flight', async () => {
		// Seed a successful turn first.
		await seedAssistantReply('asst-4', 'first reply');
		expect(store.messages).toHaveLength(2);

		// Now start a never-resolving run.
		let resolveRun: (() => void) | null = null;
		mockRunAgent.mockImplementationOnce(
			() => new Promise<void>((resolve) => { resolveRun = resolve })
		);
		store.addUserMessage('follow up');
		await Promise.resolve();
		expect(mockRunAgent).toHaveBeenCalledTimes(2);

		store.regenerate('asst-4');
		store.regenerate('asst-4');

		// Still 2 — both regens no-op'd while isRunning=true.
		expect(mockRunAgent).toHaveBeenCalledTimes(2);

		resolveRun?.();
	});

	it('regenerate is a no-op when no prior runAgent has fired (hasRun gate)', () => {
		// Codex Phase B round 1 follow-up. Calling regenerate before
		// any runAgent has captured lastRunOptions would otherwise
		// fall through to runAgent(undefined), silently re-running
		// with empty forwardedProps.
		mockRunAgent.mockReset();
		store.addUserMessage('hi');
		store.regenerate('some-id-that-may-or-may-not-exist');
		expect(mockRunAgent).not.toHaveBeenCalled();
	});
});

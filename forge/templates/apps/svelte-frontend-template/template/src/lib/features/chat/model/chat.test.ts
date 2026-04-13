import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock crypto.randomUUID before importing the store
vi.stubGlobal('crypto', { randomUUID: () => 'test-uuid-' + Math.random().toString(36).slice(2) });

const { getChatStore } = await import('$lib/features/chat/model/chat.svelte');

describe('getChatStore', () => {
	let store: ReturnType<typeof getChatStore>;

	beforeEach(() => {
		store = getChatStore();
		store.clearMessages();
		vi.useFakeTimers();
	});

	it('returns a store object with expected properties', () => {
		expect(store).toBeDefined();
		expect(store).toHaveProperty('messages');
		expect(store).toHaveProperty('isGenerating');
		expect(store).toHaveProperty('contextLabel');
		expect(typeof store.addUserMessage).toBe('function');
		expect(typeof store.clearMessages).toBe('function');
		expect(typeof store.setContext).toBe('function');
	});

	it('starts with an empty messages array', () => {
		expect(store.messages).toEqual([]);
	});

	it('starts with isGenerating false', () => {
		expect(store.isGenerating).toBe(false);
	});

	it('starts with contextLabel "General"', () => {
		expect(store.contextLabel).toBe('General');
	});

	it('addUserMessage adds a message with role "user"', () => {
		store.addUserMessage('Hello');
		expect(store.messages).toHaveLength(1);
		expect(store.messages[0].role).toBe('user');
		expect(store.messages[0].content).toBe('Hello');
		expect(store.messages[0].id).toBeDefined();
		expect(store.messages[0].timestamp).toBeInstanceOf(Date);
	});

	it('messages array grows with each addUserMessage call', () => {
		store.addUserMessage('First');
		store.addUserMessage('Second');
		// Two user messages (plus simulated responses are pending in timers)
		const userMessages = store.messages.filter((m) => m.role === 'user');
		expect(userMessages).toHaveLength(2);
	});

	it('clearMessages empties the messages array', () => {
		store.addUserMessage('Hello');
		expect(store.messages.length).toBeGreaterThan(0);
		store.clearMessages();
		expect(store.messages).toEqual([]);
	});

	it('setContext updates the contextLabel', () => {
		store.setContext('Dashboard');
		expect(store.contextLabel).toBe('Dashboard');
		store.setContext('Settings');
		expect(store.contextLabel).toBe('Settings');
	});
});

/**
 * Tests for the AG-UI agent-client reducer — focused on Pillar G.2
 * TOOL_CALL_ARGS streaming with collapsible JSON preview.
 *
 * The agent client owns a module-scoped `$state` array of
 * ``ToolCallInfo``; we drive its subscriber callbacks via a mocked
 * ``AgUiClient.runAgent`` and assert the resulting ``activeToolCalls``
 * shape. Cross-stack consistency with Vue (``useAgentClient.test.ts``)
 * + Flutter (``agent_state_reducer_test.dart``).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.stubGlobal('crypto', {
	randomUUID: () => 'test-uuid-' + Math.random().toString(36).slice(2)
});

type ToolSubscriber = Record<string, (payload: { event: Record<string, unknown> }) => void>;

// Drive the current canvas-core transport through its parsed event callback.
const runAgent = vi.fn().mockResolvedValue(undefined);
vi.mock('#canvas-core', async () => {
	const actual = await vi.importActual<typeof import('#canvas-core')>('#canvas-core');
	return {
		...actual,
		AgUiClient: class {
			constructor(private options: { onEvent: (event: ReturnType<typeof actual.parseEvent>) => void }) {}
			runAgent(payload: unknown) {
				const emit = (type: string) => ({ event }: { event: Record<string, unknown> }) => {
					this.options.onEvent(actual.parseEvent({ type, ...event }));
				};
				return runAgent(payload, {
					onToolCallStartEvent: emit('TOOL_CALL_START'),
					onToolCallArgsEvent: emit('TOOL_CALL_ARGS'),
					onToolCallEndEvent: emit('TOOL_CALL_END')
				});
			}
		}
	};
});

vi.mock('#lib/core/auth/auth.svelte.ts', () => ({
	getAuth: () => ({ getToken: async () => null })
}));

const { getAgentClient } = await import(
	'#lib/features/chat/model/agent-client.svelte.ts'
);

describe('agent-client TOOL_CALL_ARGS streaming (Pillar G.2)', () => {
	let client: ReturnType<typeof getAgentClient>;

	beforeEach(() => {
		client = getAgentClient();
		client.resetThread();
		runAgent.mockReset();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('TOOL_CALL_START seeds the activeToolCalls list', async () => {
		runAgent.mockImplementation(async (_params: unknown, subscriber: ToolSubscriber) => {
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-1', toolCallName: 'search' }
			});
		});
		await client.runAgent();
		expect(client.activeToolCalls).toHaveLength(1);
		expect(client.activeToolCalls[0]).toMatchObject({
			id: 'tc-1',
			name: 'search',
			status: 'running'
		});
		expect(client.activeToolCalls[0].argsBuffer).toBeUndefined();
	});

	it('TOOL_CALL_ARGS accumulates delta into argsBuffer', async () => {
		runAgent.mockImplementation(async (_params: unknown, subscriber: ToolSubscriber) => {
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-a', toolCallName: 'search' }
			});
			await subscriber.onToolCallArgsEvent({
				event: { toolCallId: 'tc-a', delta: '{"q":' }
			});
			await subscriber.onToolCallArgsEvent({
				event: { toolCallId: 'tc-a', delta: '"hi"}' }
			});
		});
		await client.runAgent();
		expect(client.activeToolCalls[0].argsBuffer).toBe('{"q":"hi"}');
		// argsPretty is set only on TOOL_CALL_END.
		expect(client.activeToolCalls[0].argsPretty).toBeUndefined();
	});

	it('TOOL_CALL_END pretty-prints argsBuffer via JSON.stringify', async () => {
		runAgent.mockImplementation(async (_params: unknown, subscriber: ToolSubscriber) => {
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-b', toolCallName: 'search' }
			});
			await subscriber.onToolCallArgsEvent({
				event: { toolCallId: 'tc-b', delta: '{"q":"hi","n":1}' }
			});
			await subscriber.onToolCallEndEvent({
				event: { toolCallId: 'tc-b' }
			});
		});
		await client.runAgent();
		expect(client.activeToolCalls[0].argsPretty).toBe(
			'{\n  "q": "hi",\n  "n": 1\n}'
		);
		expect(client.activeToolCalls[0].status).toBe('completed');
	});

	it('TOOL_CALL_END falls back to raw buffer on JSON parse error', async () => {
		runAgent.mockImplementation(async (_params: unknown, subscriber: ToolSubscriber) => {
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-c', toolCallName: 'search' }
			});
			await subscriber.onToolCallArgsEvent({
				event: { toolCallId: 'tc-c', delta: 'not-json{' }
			});
			await subscriber.onToolCallEndEvent({
				event: { toolCallId: 'tc-c' }
			});
		});
		await client.runAgent();
		// Parse fails → argsPretty mirrors the raw delta so the user
		// still sees *something* in the collapsible preview.
		// Use a single open-brace; a doubled open-brace would collide
		// with Copier's Jinja print delimiters at template-render time.
		expect(client.activeToolCalls[0].argsPretty).toBe('not-json{');
	});

	it('concurrent tool calls keep separate argsBuffers (no cross-contamination)', async () => {
		runAgent.mockImplementation(async (_params: unknown, subscriber: ToolSubscriber) => {
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-x', toolCallName: 'a' }
			});
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-y', toolCallName: 'b' }
			});
			await subscriber.onToolCallArgsEvent({
				event: { toolCallId: 'tc-x', delta: '{"x":1}' }
			});
			await subscriber.onToolCallArgsEvent({
				event: { toolCallId: 'tc-y', delta: '{"y":2}' }
			});
		});
		await client.runAgent();
		expect(client.activeToolCalls).toHaveLength(2);
		const x = client.activeToolCalls.find((t) => t.id === 'tc-x');
		const y = client.activeToolCalls.find((t) => t.id === 'tc-y');
		expect(x?.argsBuffer).toBe('{"x":1}');
		expect(y?.argsBuffer).toBe('{"y":2}');
	});

	it('TOOL_CALL_END with no args leaves argsPretty unset', async () => {
		runAgent.mockImplementation(async (_params: unknown, subscriber: ToolSubscriber) => {
			await subscriber.onToolCallStartEvent({
				event: { toolCallId: 'tc-empty', toolCallName: 'ping' }
			});
			await subscriber.onToolCallEndEvent({
				event: { toolCallId: 'tc-empty' }
			});
		});
		await client.runAgent();
		// No TOOL_CALL_ARGS arrived — we don't fabricate an empty preview;
		// the collapsible just hides in the UI.
		expect(client.activeToolCalls[0].argsPretty).toBeUndefined();
		expect(client.activeToolCalls[0].argsBuffer).toBeUndefined();
		expect(client.activeToolCalls[0].status).toBe('completed');
	});
});

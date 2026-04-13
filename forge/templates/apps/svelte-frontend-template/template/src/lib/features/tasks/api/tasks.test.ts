import { describe, it, expect, vi } from 'vitest';

// Mock dependencies
vi.mock('$lib/core/api/client', () => ({
	getApiClient: () => ({
		get: vi.fn().mockReturnValue({ json: vi.fn() }),
		post: vi.fn().mockReturnValue({ json: vi.fn() })
	})
}));

vi.mock('$lib/core/api/validation', () => ({
	validateResponse: vi.fn((_, raw) => raw)
}));

vi.mock('$lib/core/schemas', () => ({
	taskEnqueueResponseSchema: {},
	taskStatusResponseSchema: {}
}));

// Mock svelte/store derived
vi.mock('svelte/store', () => ({
	derived: vi.fn((_store: unknown, fn: (v: unknown) => unknown) => fn('test-task-id'))
}));

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: vi.fn((opts: unknown) => opts),
	createMutation: vi.fn((opts: Record<string, unknown>) => opts)
}));

const { createTaskStatusQuery, createEnqueueTaskMutation } = await import(
	'$lib/features/tasks/api/tasks'
);

describe('createTaskStatusQuery', () => {
	it('returns query options derived from taskIdStore', () => {
		const mockStore = { subscribe: vi.fn() };
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result).toBeDefined();
	});

	it('derived options include queryKey with task id', () => {
		const mockStore = { subscribe: vi.fn() };
		// The mock derived returns the result of the fn with 'test-task-id'
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result.queryKey).toEqual(['tasks', 'test-task-id']);
	});

	it('derived options include a queryFn', () => {
		const mockStore = { subscribe: vi.fn() };
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result.queryFn).toBeDefined();
		expect(typeof result.queryFn).toBe('function');
	});

	it('derived options include dynamic refetchInterval', () => {
		const mockStore = { subscribe: vi.fn() };
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result.refetchInterval).toBeDefined();
		expect(typeof result.refetchInterval).toBe('function');
	});

	it('refetchInterval returns false for terminal statuses', () => {
		const mockStore = { subscribe: vi.fn() };
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		const refetchFn = result.refetchInterval as (q: { state: { data?: { status: string } } }) => number | false;

		expect(refetchFn({ state: { data: { status: 'COMPLETED' } } })).toBe(false);
		expect(refetchFn({ state: { data: { status: 'FAILED' } } })).toBe(false);
		expect(refetchFn({ state: { data: { status: 'CANCELLED' } } })).toBe(false);
	});

	it('refetchInterval returns 2000 for active statuses', () => {
		const mockStore = { subscribe: vi.fn() };
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		const refetchFn = result.refetchInterval as (q: { state: { data?: { status: string } } }) => number | false;

		expect(refetchFn({ state: { data: { status: 'PENDING' } } })).toBe(2_000);
		expect(refetchFn({ state: {} })).toBe(2_000);
	});
});

describe('createEnqueueTaskMutation', () => {
	it('returns mutation options', () => {
		const result = createEnqueueTaskMutation() as unknown as Record<string, unknown>;
		expect(result).toBeDefined();
	});

	it('has a mutationFn defined', () => {
		const result = createEnqueueTaskMutation() as unknown as Record<string, unknown>;
		expect(result.mutationFn).toBeDefined();
		expect(typeof result.mutationFn).toBe('function');
	});
});

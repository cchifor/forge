import { describe, it, expect, vi } from 'vitest';

// Mock dependencies
vi.mock('#lib/core/api/client.ts', () => ({
	getApiClient: () => ({
		get: vi.fn().mockReturnValue({ json: vi.fn() }),
		post: vi.fn().mockReturnValue({ json: vi.fn() })
	})
}));

vi.mock('#lib/core/api/validation.ts', () => ({
	validateResponse: vi.fn((_, raw) => raw)
}));

vi.mock('#lib/core/schemas/index.ts', () => ({
	taskEnqueueResponseSchema: {},
	taskStatusResponseSchema: {}
}));

import { readable } from 'svelte/store';

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: vi.fn((options: () => unknown) => options()),
	createMutation: vi.fn((options: () => Record<string, unknown>) => options())
}));

const { createTaskStatusQuery, createEnqueueTaskMutation } = await import(
	'#lib/features/tasks/api/tasks.ts'
);

describe('createTaskStatusQuery', () => {
	it('returns query options derived from taskIdStore', () => {
		const mockStore = readable('test-task-id');
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result).toBeDefined();
	});

	it('derived options include queryKey with task id', () => {
		const mockStore = readable('test-task-id');
		// A real store supplies the reactive query input.
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result.queryKey).toEqual(['tasks', 'test-task-id']);
	});

	it('derived options include a queryFn', () => {
		const mockStore = readable('test-task-id');
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result.queryFn).toBeDefined();
		expect(typeof result.queryFn).toBe('function');
	});

	it('derived options include dynamic refetchInterval', () => {
		const mockStore = readable('test-task-id');
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		expect(result.refetchInterval).toBeDefined();
		expect(typeof result.refetchInterval).toBe('function');
	});

	it('refetchInterval returns false for terminal statuses', () => {
		const mockStore = readable('test-task-id');
		const result = createTaskStatusQuery(mockStore) as unknown as Record<string, unknown>;
		const refetchFn = result.refetchInterval as (q: { state: { data?: { status: string } } }) => number | false;

		expect(refetchFn({ state: { data: { status: 'COMPLETED' } } })).toBe(false);
		expect(refetchFn({ state: { data: { status: 'FAILED' } } })).toBe(false);
		expect(refetchFn({ state: { data: { status: 'CANCELLED' } } })).toBe(false);
	});

	it('refetchInterval returns 2000 for active statuses', () => {
		const mockStore = readable('test-task-id');
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

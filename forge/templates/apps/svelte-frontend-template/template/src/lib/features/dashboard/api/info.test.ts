import { describe, it, expect, vi } from 'vitest';

// Mock the dependencies
vi.mock('$lib/core/api/client', () => ({
	getApiClient: () => ({
		get: vi.fn().mockReturnValue({ json: vi.fn() })
	})
}));

vi.mock('$lib/core/api/validation', () => ({
	validateResponse: vi.fn((_, raw) => raw)
}));

vi.mock('$lib/core/schemas', () => ({
	infoResponseSchema: {}
}));

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: vi.fn((opts: Record<string, unknown>) => opts)
}));

const { createServiceInfoQuery } = await import('$lib/features/dashboard/api/info');

describe('createServiceInfoQuery', () => {
	it('returns an object with a queryKey', () => {
		const result = createServiceInfoQuery() as unknown as Record<string, unknown>;
		expect(result.queryKey).toEqual(['service', 'info']);
	});

	it('has a queryFn defined', () => {
		const result = createServiceInfoQuery() as unknown as Record<string, unknown>;
		expect(result.queryFn).toBeDefined();
		expect(typeof result.queryFn).toBe('function');
	});

	it('has staleTime set to 5 minutes', () => {
		const result = createServiceInfoQuery() as unknown as Record<string, unknown>;
		expect(result.staleTime).toBe(5 * 60_000);
	});

	it('returns all expected query option keys', () => {
		const result = createServiceInfoQuery() as unknown as Record<string, unknown>;
		expect(result).toHaveProperty('queryKey');
		expect(result).toHaveProperty('queryFn');
		expect(result).toHaveProperty('staleTime');
	});
});

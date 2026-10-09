import { describe, it, expect, vi } from 'vitest';

// Mock the dependencies so the module can be imported without real API client
vi.mock('#lib/core/api/client.ts', () => ({
	getApiClient: () => ({
		get: vi.fn().mockReturnValue({ json: vi.fn() })
	})
}));

vi.mock('#lib/core/api/validation.ts', () => ({
	validateResponse: vi.fn((_, raw) => raw)
}));

vi.mock('#lib/core/schemas/index.ts', () => ({
	livenessResponseSchema: {},
	readinessResponseSchema: {}
}));

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: vi.fn((options: () => Record<string, unknown>) => options())
}));

const { createLivenessQuery, createReadinessQuery } = await import(
	'#lib/features/dashboard/api/health.ts'
);

describe('createLivenessQuery', () => {
	it('returns an object with a queryKey', () => {
		const result = createLivenessQuery() as unknown as Record<string, unknown>;
		expect(result.queryKey).toEqual(['health', 'live']);
	});

	it('has a queryFn defined', () => {
		const result = createLivenessQuery() as unknown as Record<string, unknown>;
		expect(result.queryFn).toBeDefined();
		expect(typeof result.queryFn).toBe('function');
	});

	it('has refetchInterval set to 30 seconds', () => {
		const result = createLivenessQuery() as unknown as Record<string, unknown>;
		expect(result.refetchInterval).toBe(30_000);
	});
});

describe('createReadinessQuery', () => {
	it('returns an object with a queryKey', () => {
		const result = createReadinessQuery() as unknown as Record<string, unknown>;
		expect(result.queryKey).toEqual(['health', 'ready']);
	});

	it('has a queryFn defined', () => {
		const result = createReadinessQuery() as unknown as Record<string, unknown>;
		expect(result.queryFn).toBeDefined();
		expect(typeof result.queryFn).toBe('function');
	});

	it('has refetchInterval set to 30 seconds', () => {
		const result = createReadinessQuery() as unknown as Record<string, unknown>;
		expect(result.refetchInterval).toBe(30_000);
	});
});

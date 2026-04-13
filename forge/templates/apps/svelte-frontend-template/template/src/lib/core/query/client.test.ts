import { describe, it, expect, vi } from 'vitest';
import { QueryClient } from '@tanstack/svelte-query';
import { createQueryClient } from '$lib/core/query/client';

vi.mock('svelte-sonner', () => ({
	toast: { error: vi.fn() }
}));

describe('createQueryClient', () => {
	it('returns a QueryClient instance', () => {
		const client = createQueryClient();
		expect(client).toBeInstanceOf(QueryClient);
	});

	it('sets staleTime to 30 seconds', () => {
		const client = createQueryClient();
		const defaults = client.getDefaultOptions();
		expect(defaults.queries?.staleTime).toBe(30_000);
	});

	it('sets retry to 1', () => {
		const client = createQueryClient();
		const defaults = client.getDefaultOptions();
		expect(defaults.queries?.retry).toBe(1);
	});

	it('disables refetchOnWindowFocus', () => {
		const client = createQueryClient();
		const defaults = client.getDefaultOptions();
		expect(defaults.queries?.refetchOnWindowFocus).toBe(false);
	});
});

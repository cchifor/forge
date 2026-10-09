import { createQuery } from '@tanstack/svelte-query';
import { getApiClient } from '#lib/core/api/client.ts';
import { validateResponse } from '#lib/core/api/validation.ts';
import { livenessResponseSchema, readinessResponseSchema } from '#lib/core/schemas/index.ts';

export function createLivenessQuery() {
	const client = getApiClient();

	return createQuery(() => ({
		queryKey: ['health', 'live'] as const,
		queryFn: async () => {
			const raw = await client.get('api/v1/health/live').json();
			return validateResponse(livenessResponseSchema, raw, 'LivenessResponse');
		},
		refetchInterval: 30_000
	}));
}

export function createReadinessQuery() {
	const client = getApiClient();

	return createQuery(() => ({
		queryKey: ['health', 'ready'] as const,
		queryFn: async () => {
			const raw = await client.get('api/v1/health/ready').json();
			return validateResponse(readinessResponseSchema, raw, 'ReadinessResponse');
		},
		refetchInterval: 30_000
	}));
}

import { createQuery } from '@tanstack/svelte-query';
import { getApiClient } from '#lib/core/api/client.ts';
import { validateResponse } from '#lib/core/api/validation.ts';
import { infoResponseSchema } from '#lib/core/schemas/index.ts';

export function createServiceInfoQuery() {
	const client = getApiClient();

	return createQuery(() => ({
		queryKey: ['service', 'info'] as const,
		queryFn: async () => {
			const raw = await client.get('api/v1/info').json();
			return validateResponse(infoResponseSchema, raw, 'InfoResponse');
		},
		staleTime: 5 * 60_000
	}));
}

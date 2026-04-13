import { QueryClient } from '@tanstack/svelte-query';
import { toast } from 'svelte-sonner';

export function createQueryClient(): QueryClient {
	return new QueryClient({
		defaultOptions: {
			queries: {
				staleTime: 30_000,
				retry: 1,
				refetchOnWindowFocus: false
			},
			mutations: {
				onError: (error) => {
					const message =
						error instanceof Error ? error.message : 'An unexpected error occurred';
					toast.error(message);
				}
			}
		}
	});
}

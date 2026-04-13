import { createQuery, createMutation } from '@tanstack/svelte-query';
import { derived, type Readable } from 'svelte/store';
import { getApiClient } from '$lib/core/api/client';
import { validateResponse } from '$lib/core/api/validation';
import { taskEnqueueResponseSchema, taskStatusResponseSchema } from '$lib/core/schemas';
import type { API } from '$lib/core/api/namespace';

export function createTaskStatusQuery(taskIdStore: Readable<string | null>) {
	const client = getApiClient();

	const options = derived(taskIdStore, ($taskId) => ({
		queryKey: ['tasks', $taskId] as const,
		queryFn: async () => {
			const raw = await client.get(`api/v1/tasks/${$taskId}`).json();
			return validateResponse(taskStatusResponseSchema, raw, 'TaskStatusResponse');
		},
		enabled: !!$taskId,
		refetchInterval: (query: { state: { data?: { status: string } } }) => {
			const status = query.state.data?.status;
			if (status === 'COMPLETED' || status === 'FAILED' || status === 'CANCELLED') {
				return false;
			}
			return 2_000;
		}
	}));

	return createQuery(options);
}

export function createEnqueueTaskMutation() {
	const client = getApiClient();

	return createMutation({
		mutationFn: async (data: API.TaskEnqueueRequest) => {
			const raw = await client.post('api/v1/tasks', { json: data }).json();
			return validateResponse(taskEnqueueResponseSchema, raw, 'TaskEnqueueResponse');
		}
	});
}

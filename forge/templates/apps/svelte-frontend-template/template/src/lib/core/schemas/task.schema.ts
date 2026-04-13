import { z } from 'zod';

export const taskEnqueueResponseSchema = z.object({
	id: z.string(),
	task_type: z.string(),
	status: z.string()
});

export const taskStatusResponseSchema = z.object({
	id: z.string(),
	task_type: z.string(),
	status: z.string(),
	payload: z.record(z.unknown()).nullable(),
	result: z.record(z.unknown()).nullable(),
	error: z.string().nullable(),
	attempts: z.number().int(),
	max_retries: z.number().int(),
	created_at: z.string().nullable(),
	started_at: z.string().nullable(),
	completed_at: z.string().nullable()
});

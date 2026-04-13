import { z } from 'zod';

export const healthStatusSchema = z.enum(['UP', 'DOWN', 'DEGRADED']);

export const componentStatusSchema = z.object({
	status: healthStatusSchema,
	latency_ms: z.number().nullable(),
	details: z.record(z.unknown()).nullable()
});

export const livenessResponseSchema = z.object({
	status: healthStatusSchema,
	details: z.string()
});

export const readinessResponseSchema = z.object({
	status: healthStatusSchema,
	components: z.record(componentStatusSchema),
	system_info: z.record(z.string())
});

export const infoResponseSchema = z.object({
	title: z.string(),
	version: z.string(),
	description: z.string()
});

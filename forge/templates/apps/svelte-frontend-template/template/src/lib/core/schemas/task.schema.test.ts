import { describe, it, expect } from 'vitest';
import {
	taskEnqueueResponseSchema,
	taskStatusResponseSchema
} from '$lib/core/schemas/task.schema';

describe('taskEnqueueResponseSchema', () => {
	it('parses a valid enqueue response', () => {
		const data = { id: 'abc-123', task_type: 'email', status: 'queued' };
		expect(taskEnqueueResponseSchema.parse(data)).toEqual(data);
	});

	it('rejects when id is missing', () => {
		const result = taskEnqueueResponseSchema.safeParse({
			task_type: 'email',
			status: 'queued'
		});
		expect(result.success).toBe(false);
	});

	it('rejects when status is missing', () => {
		const result = taskEnqueueResponseSchema.safeParse({
			id: 'abc-123',
			task_type: 'email'
		});
		expect(result.success).toBe(false);
	});
});

describe('taskStatusResponseSchema', () => {
	it('parses a valid status response with all fields', () => {
		const data = {
			id: 'abc-123',
			task_type: 'email',
			status: 'completed',
			payload: { to: 'user@test.com' },
			result: { sent: true },
			error: null,
			attempts: 1,
			max_retries: 3,
			created_at: '2025-01-01T00:00:00Z',
			started_at: '2025-01-01T00:00:01Z',
			completed_at: '2025-01-01T00:00:02Z'
		};
		expect(taskStatusResponseSchema.parse(data)).toEqual(data);
	});

	it('accepts null for nullable fields', () => {
		const data = {
			id: 'abc-123',
			task_type: 'email',
			status: 'queued',
			payload: null,
			result: null,
			error: null,
			attempts: 0,
			max_retries: 3,
			created_at: null,
			started_at: null,
			completed_at: null
		};
		expect(taskStatusResponseSchema.parse(data)).toEqual(data);
	});

	it('rejects when required fields are missing', () => {
		const result = taskStatusResponseSchema.safeParse({
			id: 'abc-123',
			task_type: 'email'
		});
		expect(result.success).toBe(false);
	});

	it('rejects when attempts is not an integer', () => {
		const result = taskStatusResponseSchema.safeParse({
			id: 'abc-123',
			task_type: 'email',
			status: 'queued',
			payload: null,
			result: null,
			error: null,
			attempts: 1.5,
			max_retries: 3,
			created_at: null,
			started_at: null,
			completed_at: null
		});
		expect(result.success).toBe(false);
	});
});

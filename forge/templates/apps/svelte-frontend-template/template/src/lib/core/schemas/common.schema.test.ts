import { describe, it, expect } from 'vitest';
import { z } from 'zod';
import { paginatedResponseSchema, apiErrorSchema } from '$lib/core/schemas/common.schema';

describe('paginatedResponseSchema', () => {
	const schema = paginatedResponseSchema(z.object({ id: z.number() }));

	it('parses valid paginated data', () => {
		const data = { items: [{ id: 1 }, { id: 2 }], total: 10, skip: 0, limit: 20, has_more: true };
		expect(schema.parse(data)).toEqual(data);
	});

	it('accepts empty items array', () => {
		const data = { items: [], total: 0, skip: 0, limit: 20, has_more: false };
		expect(schema.parse(data)).toEqual(data);
	});

	it('rejects when items are missing', () => {
		const result = schema.safeParse({ total: 10, skip: 0, limit: 20, has_more: false });
		expect(result.success).toBe(false);
	});

	it('rejects when total is not an integer', () => {
		const result = schema.safeParse({
			items: [],
			total: 1.5,
			skip: 0,
			limit: 20,
			has_more: false
		});
		expect(result.success).toBe(false);
	});

	it('rejects when item shape does not match', () => {
		const result = schema.safeParse({
			items: [{ name: 'wrong' }],
			total: 1,
			skip: 0,
			limit: 20,
			has_more: false
		});
		expect(result.success).toBe(false);
	});
});

describe('apiErrorSchema', () => {
	it('parses a valid error object', () => {
		const data = { message: 'Not found', type: 'not_found', detail: null };
		expect(apiErrorSchema.parse(data)).toEqual(data);
	});

	it('parses when detail is an object', () => {
		const data = { message: 'Bad request', type: 'validation', detail: { field: 'name' } };
		expect(apiErrorSchema.parse(data)).toEqual(data);
	});

	it('allows detail to be omitted', () => {
		const data = { message: 'Error', type: 'unknown' };
		expect(apiErrorSchema.parse(data)).toEqual(data);
	});

	it('rejects when message is missing', () => {
		const result = apiErrorSchema.safeParse({ type: 'error' });
		expect(result.success).toBe(false);
	});

	it('rejects when type is missing', () => {
		const result = apiErrorSchema.safeParse({ message: 'Error' });
		expect(result.success).toBe(false);
	});
});

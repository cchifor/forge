import { describe, it, expect, vi } from 'vitest';
import { z } from 'zod';
import { validateResponse, reportValidationFailure } from '$lib/core/api/validation';

vi.mock('svelte-sonner', () => ({
	toast: { error: vi.fn() }
}));

import { toast } from 'svelte-sonner';

const testSchema = z.object({
	id: z.number(),
	name: z.string()
});

describe('validateResponse', () => {
	it('returns parsed data when input is valid', async () => {
		const data = { id: 1, name: 'test' };
		const result = await validateResponse(testSchema, data, 'TestLabel');
		expect(result).toEqual({ id: 1, name: 'test' });
	});

	it('throws and reports when input is invalid', async () => {
		const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
		await expect(
			validateResponse(testSchema, { id: 'bad', name: 42 }, 'TestLabel')
		).rejects.toThrow();
		expect(spy).toHaveBeenCalled();
		spy.mockRestore();
	});

	it('strips unknown keys via schema parse', async () => {
		const data = { id: 1, name: 'test', extra: true };
		const result = await validateResponse(testSchema, data, 'TestLabel');
		expect(result).toEqual({ id: 1, name: 'test' });
	});
});

describe('reportValidationFailure', () => {
	it('logs formatted error to console.error', () => {
		const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
		const zodError = new z.ZodError([
			{
				code: 'invalid_type',
				expected: 'string',
				received: 'number',
				path: ['name'],
				message: 'Expected string, received number'
			}
		]);
		reportValidationFailure('TestLabel', zodError);
		expect(spy).toHaveBeenCalledWith(
			expect.stringContaining('[API Contract Violation] TestLabel')
		);
		spy.mockRestore();
	});

	it('calls toast.error with the label', () => {
		vi.spyOn(console, 'error').mockImplementation(() => {});
		const zodError = new z.ZodError([
			{
				code: 'invalid_type',
				expected: 'string',
				received: 'number',
				path: ['field'],
				message: 'Expected string, received number'
			}
		]);
		reportValidationFailure('SchemaName', zodError);
		expect(toast.error).toHaveBeenCalledWith('Backend contract violation: SchemaName');
		vi.restoreAllMocks();
	});

	it('includes field paths in the logged message', () => {
		const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
		const zodError = new z.ZodError([
			{
				code: 'invalid_type',
				expected: 'number',
				received: 'string',
				path: ['data', 'count'],
				message: 'Expected number, received string'
			}
		]);
		reportValidationFailure('Nested', zodError);
		expect(spy).toHaveBeenCalledWith(expect.stringContaining('data.count'));
		spy.mockRestore();
	});
});

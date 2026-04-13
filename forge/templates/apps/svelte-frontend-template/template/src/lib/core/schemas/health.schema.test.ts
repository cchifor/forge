import { describe, it, expect } from 'vitest';
import {
	healthStatusSchema,
	componentStatusSchema,
	livenessResponseSchema,
	readinessResponseSchema,
	infoResponseSchema
} from '$lib/core/schemas/health.schema';

describe('healthStatusSchema', () => {
	it.each(['UP', 'DOWN', 'DEGRADED'])('accepts "%s"', (value) => {
		expect(healthStatusSchema.parse(value)).toBe(value);
	});

	it('rejects invalid status strings', () => {
		expect(healthStatusSchema.safeParse('UNKNOWN').success).toBe(false);
		expect(healthStatusSchema.safeParse('up').success).toBe(false);
		expect(healthStatusSchema.safeParse('').success).toBe(false);
	});
});

describe('componentStatusSchema', () => {
	it('parses a valid component', () => {
		const data = { status: 'UP', latency_ms: 12, details: null };
		expect(componentStatusSchema.parse(data)).toEqual(data);
	});

	it('accepts null latency_ms and null details', () => {
		const data = { status: 'DOWN', latency_ms: null, details: null };
		expect(componentStatusSchema.parse(data)).toEqual(data);
	});

	it('rejects missing status', () => {
		const result = componentStatusSchema.safeParse({ latency_ms: 10, details: null });
		expect(result.success).toBe(false);
	});
});

describe('livenessResponseSchema', () => {
	it('parses a valid liveness response', () => {
		const data = { status: 'UP', details: 'Service is alive' };
		expect(livenessResponseSchema.parse(data)).toEqual(data);
	});

	it('rejects when details is missing', () => {
		const result = livenessResponseSchema.safeParse({ status: 'UP' });
		expect(result.success).toBe(false);
	});
});

describe('readinessResponseSchema', () => {
	it('parses a valid readiness response', () => {
		const data = {
			status: 'UP',
			components: {
				database: { status: 'UP', latency_ms: 5, details: null }
			},
			system_info: { version: '1.0.0' }
		};
		expect(readinessResponseSchema.parse(data)).toEqual(data);
	});

	it('rejects when components is missing', () => {
		const result = readinessResponseSchema.safeParse({
			status: 'UP',
			system_info: { version: '1.0.0' }
		});
		expect(result.success).toBe(false);
	});
});

describe('infoResponseSchema', () => {
	it('parses a valid info response', () => {
		const data = { title: 'My API', version: '2.0.0', description: 'A test API' };
		expect(infoResponseSchema.parse(data)).toEqual(data);
	});

	it('rejects when version is missing', () => {
		const result = infoResponseSchema.safeParse({ title: 'My API', description: 'A test API' });
		expect(result.success).toBe(false);
	});
});

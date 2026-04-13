import { describe, it, expect } from 'vitest';
import { categorizeError, userFacingMessage } from '$lib/core/errors';

describe('categorizeError', () => {
	it('returns "not-found" for 404', () => {
		expect(categorizeError(404)).toBe('not-found');
	});

	it('returns "forbidden" for 403', () => {
		expect(categorizeError(403)).toBe('forbidden');
	});

	it('returns "server" for 500', () => {
		expect(categorizeError(500)).toBe('server');
	});

	it('returns "server" for 502 and other 5xx codes', () => {
		expect(categorizeError(502)).toBe('server');
		expect(categorizeError(503)).toBe('server');
	});

	it('returns "unknown" for unrecognized status codes', () => {
		expect(categorizeError(400)).toBe('unknown');
		expect(categorizeError(401)).toBe('unknown');
		expect(categorizeError(409)).toBe('unknown');
		expect(categorizeError(422)).toBe('unknown');
	});
});

describe('userFacingMessage', () => {
	it('returns not-found message for 404', () => {
		expect(userFacingMessage(404)).toBe(
			'The page or resource you requested could not be found.'
		);
	});

	it('returns forbidden message for 403', () => {
		expect(userFacingMessage(403)).toBe(
			'You do not have permission to access this resource.'
		);
	});

	it('returns server message for 500', () => {
		expect(userFacingMessage(500)).toBe(
			'Something went wrong on our end. Please try again later.'
		);
	});

	it('returns default message for unknown status without fallback', () => {
		expect(userFacingMessage(418)).toBe('An unexpected error occurred.');
	});

	it('returns custom fallback for unknown status when provided', () => {
		expect(userFacingMessage(418, 'Custom error')).toBe('Custom error');
	});

	it('ignores fallback when status maps to a known category', () => {
		expect(userFacingMessage(404, 'Custom error')).toBe(
			'The page or resource you requested could not be found.'
		);
	});
});

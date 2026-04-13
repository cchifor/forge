import { describe, it, expect } from 'vitest';
import { cn } from '$lib/shared/lib/utils';

describe('cn', () => {
	it('merges class names', () => {
		expect(cn('foo', 'bar')).toBe('foo bar');
	});

	it('handles empty inputs', () => {
		expect(cn()).toBe('');
		expect(cn('')).toBe('');
		expect(cn(undefined, null, false)).toBe('');
	});

	it('resolves Tailwind conflicts by keeping the last value', () => {
		expect(cn('p-4', 'p-2')).toBe('p-2');
		expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500');
	});

	it('handles conditional class names', () => {
		const isActive = true;
		const isDisabled = false;
		expect(cn('base', isActive && 'active', isDisabled && 'disabled')).toBe('base active');
	});
});

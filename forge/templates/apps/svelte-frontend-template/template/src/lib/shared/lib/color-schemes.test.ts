import { describe, it, expect } from 'vitest';
import { colorSchemes, getSchemeByName } from '$lib/shared/lib/color-schemes';

describe('colorSchemes', () => {
	it('contains multiple color schemes', () => {
		expect(colorSchemes.length).toBeGreaterThan(0);
		expect(colorSchemes.length).toBe(20);
	});

	it('each scheme has a name and label', () => {
		for (const scheme of colorSchemes) {
			expect(scheme.name).toBeTruthy();
			expect(scheme.label).toBeTruthy();
		}
	});

	it('each scheme has light and dark primary HSL values', () => {
		for (const scheme of colorSchemes) {
			expect(scheme.lightPrimary).toBeTruthy();
			expect(scheme.darkPrimary).toBeTruthy();
			// HSL format: "H S% L%"
			expect(scheme.lightPrimary).toMatch(/^\d+\s+\d+%?\s+\d+%$/);
			expect(scheme.darkPrimary).toMatch(/^\d+\s+\d+%?\s+\d+%$/);
		}
	});

	it('each scheme has light and dark container HSL values', () => {
		for (const scheme of colorSchemes) {
			expect(scheme.lightContainer).toBeTruthy();
			expect(scheme.darkContainer).toBeTruthy();
		}
	});
});

describe('getSchemeByName', () => {
	it('returns the correct scheme for "blue"', () => {
		const scheme = getSchemeByName('blue');
		expect(scheme.name).toBe('blue');
		expect(scheme.label).toBe('Blue');
	});

	it('returns the correct scheme for "red"', () => {
		const scheme = getSchemeByName('red');
		expect(scheme.name).toBe('red');
		expect(scheme.label).toBe('Red');
	});

	it('returns the default (first) scheme for an invalid name', () => {
		const scheme = getSchemeByName('nonexistent');
		expect(scheme).toBe(colorSchemes[0]);
		expect(scheme.name).toBe('blue');
	});
});

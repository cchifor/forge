import { describe, it, expect } from 'vitest';
import { DesignTokens } from '$lib/shared/lib/design-tokens';

describe('DesignTokens', () => {
	it('has positive spacing values in monotonically increasing order', () => {
		const spacings = [
			DesignTokens.p4,
			DesignTokens.p8,
			DesignTokens.p12,
			DesignTokens.p16,
			DesignTokens.p20,
			DesignTokens.p24,
			DesignTokens.p32,
			DesignTokens.p48,
			DesignTokens.p64
		];
		for (let i = 0; i < spacings.length; i++) {
			expect(spacings[i]).toBeGreaterThan(0);
			if (i > 0) {
				expect(spacings[i]).toBeGreaterThan(spacings[i - 1]);
			}
		}
	});

	it('has positive border radius values', () => {
		expect(DesignTokens.radiusSmall).toBeGreaterThan(0);
		expect(DesignTokens.radiusMedium).toBeGreaterThan(0);
		expect(DesignTokens.radiusLarge).toBeGreaterThan(0);
		expect(DesignTokens.radiusXLarge).toBeGreaterThan(0);
		expect(DesignTokens.radiusSmall).toBeLessThan(DesignTokens.radiusMedium);
		expect(DesignTokens.radiusMedium).toBeLessThan(DesignTokens.radiusLarge);
	});

	it('has positive animation durations', () => {
		expect(DesignTokens.durationFast).toBeGreaterThan(0);
		expect(DesignTokens.durationNormal).toBeGreaterThan(0);
		expect(DesignTokens.durationSlow).toBeGreaterThan(0);
		expect(DesignTokens.durationDebounce).toBeGreaterThan(0);
		expect(DesignTokens.durationFast).toBeLessThan(DesignTokens.durationNormal);
		expect(DesignTokens.durationNormal).toBeLessThan(DesignTokens.durationSlow);
	});

	it('has reasonable sidebar layout dimensions', () => {
		expect(DesignTokens.sidebarCollapsedWidth).toBeGreaterThan(0);
		expect(DesignTokens.sidebarExpandedWidth).toBeGreaterThan(DesignTokens.sidebarCollapsedWidth);
	});

	it('has reasonable chat layout dimensions', () => {
		expect(DesignTokens.minChatWidth).toBeGreaterThan(0);
		expect(DesignTokens.maxChatWidth).toBeGreaterThan(DesignTokens.minChatWidth);
		expect(DesignTokens.chatDrawerWidth).toBeGreaterThanOrEqual(DesignTokens.minChatWidth);
		expect(DesignTokens.chatDrawerWidth).toBeLessThanOrEqual(DesignTokens.maxChatWidth);
	});

	it('has positive header and navigation dimensions', () => {
		expect(DesignTokens.headerHeight).toBeGreaterThan(0);
		expect(DesignTokens.bottomNavHeight).toBeGreaterThan(0);
		expect(DesignTokens.minMainAreaWidth).toBeGreaterThan(0);
	});
});

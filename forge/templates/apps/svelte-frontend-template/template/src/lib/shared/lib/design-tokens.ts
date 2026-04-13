export const DesignTokens = {
	// Spacing scale
	p4: 4,
	p8: 8,
	p12: 12,
	p16: 16,
	p20: 20,
	p24: 24,
	p32: 32,
	p48: 48,
	p64: 64,

	// Icon sizes
	iconXS: 14,
	iconSM: 16,
	iconMD: 20,
	iconLG: 24,
	iconXL: 48,
	iconHero: 80,

	// Border radii
	radiusSmall: 8,
	radiusMedium: 12,
	radiusLarge: 16,
	radiusXLarge: 20,

	// Animation durations (ms)
	durationFast: 100,
	durationNormal: 200,
	durationSlow: 300,
	durationDebounce: 400,

	// Layout dimensions
	sidebarCollapsedWidth: 72,
	sidebarExpandedWidth: 240,
	sidebarIconColumnWidth: 56,
	headerHeight: 56,
	bottomNavHeight: 64,
	minMainAreaWidth: 300,
	minChatWidth: 280,
	maxChatWidth: 480,
	chatDrawerWidth: 360,
	splitterWidth: 8,
	selectionIndicatorWidth: 3,
	selectionIndicatorHeight: 20
} as const;

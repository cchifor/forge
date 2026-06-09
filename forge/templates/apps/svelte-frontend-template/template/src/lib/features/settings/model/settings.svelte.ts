import { getSchemeByName } from '$lib/shared/lib/color-schemes';

export type ThemeMode = 'light' | 'dark' | 'system';
export type DarkVariant = 'standard' | 'oled';
export type TextSize = 'sm' | 'md' | 'lg';

export const TEXT_SIZES: Record<TextSize, { label: string; rem: string }> = {
	sm: { label: 'Small', rem: '0.9375rem' },
	md: { label: 'Medium', rem: '1rem' },
	lg: { label: 'Large', rem: '1.125rem' }
};

let theme = $state<ThemeMode>((localStorage.getItem('theme') as ThemeMode) || 'system');
let colorScheme = $state(localStorage.getItem('color-scheme') || 'blue');
let darkVariant = $state<DarkVariant>(
	(localStorage.getItem('dark-variant') as DarkVariant) || 'standard'
);
let textSize = $state<TextSize>((localStorage.getItem('text-size') as TextSize) || 'md');

const resolvedTheme = $derived<'light' | 'dark'>(
	theme === 'system'
		? window.matchMedia('(prefers-color-scheme: dark)').matches
			? 'dark'
			: 'light'
		: theme
);

function setTheme(newTheme: ThemeMode) {
	theme = newTheme;
	localStorage.setItem('theme', newTheme);
	applyTheme();
}

function setColorScheme(name: string) {
	colorScheme = name;
	localStorage.setItem('color-scheme', name);
	applyTheme();
}

function setDarkVariant(variant: DarkVariant) {
	darkVariant = variant;
	localStorage.setItem('dark-variant', variant);
	applyTheme();
}

function setTextSize(size: TextSize) {
	textSize = size;
	localStorage.setItem('text-size', size);
	applyTheme();
}

function applyTheme() {
	const isDark = resolvedTheme === 'dark';

	// Toggle .dark class
	document.documentElement.classList.toggle('dark', isDark);

	// Toggle .oled class
	document.documentElement.classList.toggle('oled', isDark && darkVariant === 'oled');

	// Apply color scheme HSL values
	const scheme = getSchemeByName(colorScheme);
	const primaryHsl = isDark ? scheme.darkPrimary : scheme.lightPrimary;
	document.documentElement.style.setProperty('--primary', primaryHsl);

	// For light mode with colored primary, use white foreground; for dark mode, use dark foreground
	if (colorScheme !== 'blue') {
		document.documentElement.style.setProperty(
			'--primary-foreground',
			isDark ? '240 5.9% 10%' : '0 0% 98%'
		);
	} else {
		// Reset to default for blue (the default theme)
		document.documentElement.style.removeProperty('--primary');
		document.documentElement.style.removeProperty('--primary-foreground');
	}

	// Apply text size preference
	document.documentElement.dataset.textSize = textSize;
	document.documentElement.style.setProperty('--font-size', TEXT_SIZES[textSize].rem);
}

export function getSettingsStore() {
	return {
		get theme() {
			return theme;
		},
		get resolvedTheme() {
			return resolvedTheme;
		},
		get colorScheme() {
			return colorScheme;
		},
		get darkVariant() {
			return darkVariant;
		},
		get textSize() {
			return textSize;
		},
		setTheme,
		setColorScheme,
		setDarkVariant,
		setTextSize,
		applyTheme
	};
}

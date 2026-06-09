import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock localStorage before importing the store
const storage = new Map<string, string>();
vi.stubGlobal('localStorage', {
	getItem: (k: string) => storage.get(k) ?? null,
	setItem: (k: string, v: string) => storage.set(k, v),
	removeItem: (k: string) => storage.delete(k)
});

// Mock document.documentElement for applyTheme
vi.stubGlobal('document', {
	documentElement: {
		classList: {
			toggle: vi.fn(),
			add: vi.fn(),
			remove: vi.fn()
		},
		style: {
			setProperty: vi.fn(),
			removeProperty: vi.fn()
		},
		dataset: {} as Record<string, string>
	}
});

// Mock matchMedia for the resolvedTheme $derived
vi.stubGlobal('window', {
	...globalThis.window,
	matchMedia: vi.fn().mockReturnValue({
		matches: false,
		addEventListener: vi.fn(),
		removeEventListener: vi.fn()
	})
});

// Type-only import; the runtime instance is (re)imported per test below.
import type { getSettingsStore as GetSettingsStore } from '$lib/features/settings/model/settings.svelte';

describe('getSettingsStore', () => {
	let store: ReturnType<typeof GetSettingsStore>;

	beforeEach(async () => {
		storage.clear();
		vi.clearAllMocks();
		// The store's $state lives at module scope; reset the module registry so
		// each test re-evaluates it fresh (reading the just-cleared storage) —
		// otherwise a textSize/theme set in one test leaks into the next.
		vi.resetModules();
		const mod = await import('$lib/features/settings/model/settings.svelte');
		store = mod.getSettingsStore();
	});

	it('returns a store object with expected properties', () => {
		expect(store).toBeDefined();
		expect(store).toHaveProperty('theme');
		expect(store).toHaveProperty('colorScheme');
		expect(store).toHaveProperty('darkVariant');
		expect(store).toHaveProperty('textSize');
		expect(typeof store.setTheme).toBe('function');
		expect(typeof store.setColorScheme).toBe('function');
		expect(typeof store.setDarkVariant).toBe('function');
		expect(typeof store.setTextSize).toBe('function');
		expect(typeof store.applyTheme).toBe('function');
	});

	it('defaults theme to "system" when localStorage is empty', () => {
		expect(store.theme).toBe('system');
	});

	it('defaults colorScheme to "blue" when localStorage is empty', () => {
		expect(store.colorScheme).toBe('blue');
	});

	it('defaults darkVariant to "standard" when localStorage is empty', () => {
		expect(store.darkVariant).toBe('standard');
	});

	it('setTheme updates the theme value', () => {
		store.setTheme('dark');
		expect(store.theme).toBe('dark');
	});

	it('setTheme persists to localStorage', () => {
		store.setTheme('light');
		expect(storage.get('theme')).toBe('light');
	});

	it('setColorScheme updates the colorScheme value', () => {
		store.setColorScheme('red');
		expect(store.colorScheme).toBe('red');
	});

	it('setColorScheme persists to localStorage', () => {
		store.setColorScheme('sakura');
		expect(storage.get('color-scheme')).toBe('sakura');
	});

	it('setDarkVariant updates the darkVariant value', () => {
		store.setDarkVariant('oled');
		expect(store.darkVariant).toBe('oled');
	});

	it('defaults textSize to "md" when localStorage is empty', () => {
		expect(store.textSize).toBe('md');
	});

	it('setTextSize updates the textSize value', () => {
		store.setTextSize('lg');
		expect(store.textSize).toBe('lg');
	});

	it('setTextSize persists to localStorage', () => {
		store.setTextSize('sm');
		expect(storage.get('text-size')).toBe('sm');
	});

	it('setTextSize applies the --font-size CSS variable', () => {
		store.setTextSize('sm');
		// Percentage of the browser default, applied to the root so rem utilities scale.
		expect(document.documentElement.style.setProperty).toHaveBeenCalledWith(
			'--font-size',
			'93.75%'
		);
	});

	it('applyTheme toggles the dark class on document.documentElement', () => {
		store.applyTheme();
		expect(document.documentElement.classList.toggle).toHaveBeenCalledWith('dark', expect.any(Boolean));
	});
});

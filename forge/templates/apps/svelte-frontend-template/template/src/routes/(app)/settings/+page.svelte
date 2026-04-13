<script lang="ts">
	import { Sun, Moon, Monitor } from 'lucide-svelte';
	import {
		getSettingsStore,
		type ThemeMode,
		ColorSchemePicker,
		DarkVariantSelector
	} from '$lib/features/settings';
	import { colorSchemes } from '$lib/shared/lib/color-schemes';

	const settings = getSettingsStore();

	const themeOptions: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
		{ value: 'light', label: 'Light', icon: Sun },
		{ value: 'dark', label: 'Dark', icon: Moon },
		{ value: 'system', label: 'System', icon: Monitor }
	];
</script>

<div class="space-y-6">
	<div>
		<h1 class="text-3xl font-bold tracking-tight">Settings</h1>
		<p class="text-muted-foreground">Manage your application preferences</p>
	</div>

	<!-- Appearance -->
	<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
		<div class="p-6">
			<h3 class="text-lg font-semibold leading-none tracking-tight">Appearance</h3>
			<p class="mt-1.5 text-sm text-muted-foreground">
				Choose how the application looks. Select a theme or let it follow your system
				preference.
			</p>
		</div>
		<div class="p-6 pt-0">
			<div class="space-y-6">
				<!-- Theme Mode -->
				<div>
					<span class="text-sm font-medium">Theme</span>
					<p class="mb-3 text-sm text-muted-foreground">
						Select the color scheme for the interface
					</p>
					<div class="inline-flex items-center rounded-lg border bg-muted p-1">
						{#each themeOptions as option}
							<button
								class="inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors {settings.theme ===
								option.value
									? 'bg-background text-foreground shadow-sm'
									: 'text-muted-foreground hover:text-foreground'}"
								onclick={() => settings.setTheme(option.value)}
							>
								<option.icon class="h-4 w-4" />
								{option.label}
							</button>
						{/each}
					</div>
				</div>

				<!-- Dark Mode Variant -->
				<div>
					<span class="text-sm font-medium">Dark Mode Variant</span>
					<p class="mb-3 text-sm text-muted-foreground">
						Choose between standard dark and OLED-optimized black
					</p>
					<DarkVariantSelector
						value={settings.darkVariant}
						onchange={(v) => settings.setDarkVariant(v as 'standard' | 'oled')}
						disabled={settings.resolvedTheme === 'light'}
					/>
				</div>

				<!-- Color Scheme -->
				<div>
					<span class="text-sm font-medium">Color Scheme</span>
					<p class="mb-3 text-sm text-muted-foreground">
						Pick a primary accent color for the interface
					</p>
					<ColorSchemePicker
						currentScheme={settings.colorScheme}
						schemes={colorSchemes}
						onselect={(name) => settings.setColorScheme(name)}
					/>
				</div>
			</div>
		</div>
	</div>

	<!-- Notifications -->
	<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
		<div class="p-6">
			<h3 class="text-lg font-semibold leading-none tracking-tight">Notifications</h3>
			<p class="mt-1.5 text-sm text-muted-foreground">
				Configure how you receive notifications
			</p>
		</div>
		<div class="p-6 pt-0">
			<p class="text-sm text-muted-foreground">Notification preferences coming soon.</p>
		</div>
	</div>

	<div class="h-px bg-border"></div>

	<!-- About -->
	<div class="rounded-lg border bg-card text-card-foreground shadow-sm">
		<div class="p-6">
			<h3 class="text-lg font-semibold leading-none tracking-tight">About</h3>
		</div>
		<div class="p-6 pt-0">
			<dl class="space-y-2 text-sm">
				<div class="flex justify-between">
					<dt class="text-muted-foreground">Application</dt>
					<dd class="font-medium">Svelte Frontend</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-muted-foreground">Version</dt>
					<dd class="font-medium">0.1.0</dd>
				</div>
				<div class="flex justify-between">
					<dt class="text-muted-foreground">Framework</dt>
					<dd class="font-medium">SvelteKit + Svelte 5</dd>
				</div>
			</dl>
		</div>
	</div>
</div>

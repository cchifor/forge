<script lang="ts">
	import { Check } from 'lucide-svelte';
	import type { ColorScheme } from '$lib/shared/lib/color-schemes';
	import { getSettingsStore } from '$lib/features/settings';

	let {
		currentScheme,
		schemes,
		onselect
	}: {
		currentScheme: string;
		schemes: ColorScheme[];
		onselect: (name: string) => void;
	} = $props();

	const settings = getSettingsStore();
	const isDark = $derived(settings.resolvedTheme === 'dark');
</script>

<div class="flex flex-wrap gap-2">
	{#each schemes as scheme}
		<button
			class="relative flex h-10 w-10 items-center justify-center rounded-full transition-shadow {currentScheme ===
			scheme.name
				? 'ring-2 ring-primary ring-offset-2 ring-offset-background'
				: 'hover:ring-2 hover:ring-muted hover:ring-offset-1 hover:ring-offset-background'}"
			style="background-color: hsl({isDark ? scheme.darkPrimary : scheme.lightPrimary})"
			title={scheme.label}
			onclick={() => onselect(scheme.name)}
		>
			{#if currentScheme === scheme.name}
				<Check class="h-4 w-4 text-white" />
			{/if}
		</button>
	{/each}
</div>

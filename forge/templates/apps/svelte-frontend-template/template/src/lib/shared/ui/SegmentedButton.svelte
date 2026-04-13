<script lang="ts">
	import type { Component } from 'svelte';

	let {
		options,
		value = $bindable(''),
		onchange
	}: {
		options: Array<{ value: string; label: string; icon?: Component }>;
		value: string;
		onchange?: (value: string) => void;
	} = $props();
</script>

<div class="inline-flex items-center rounded-lg border bg-muted p-1">
	{#each options as option}
		<button
			class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors
				{value === option.value
				? 'bg-background text-foreground shadow-sm'
				: 'text-muted-foreground hover:text-foreground'}"
			onclick={() => {
				value = option.value;
				onchange?.(option.value);
			}}
		>
			{#if option.icon}
				{@const Icon = option.icon}
				<Icon class="h-4 w-4" />
			{/if}
			{option.label}
		</button>
	{/each}
</div>

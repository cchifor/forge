<script lang="ts">
	import { Search, X } from 'lucide-svelte';

	let {
		value = $bindable(''),
		placeholder = 'Search...',
		debounceMs = 300,
		onchange
	}: {
		value: string;
		placeholder?: string;
		debounceMs?: number;
		onchange?: (value: string) => void;
	} = $props();

	let timeout: ReturnType<typeof setTimeout>;
	$effect(() => {
		const v = value;
		clearTimeout(timeout);
		timeout = setTimeout(() => onchange?.(v), debounceMs);
		return () => clearTimeout(timeout);
	});
</script>

<div class="relative">
	<Search class="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
	<input
		type="text"
		bind:value
		{placeholder}
		class="flex h-10 w-full rounded-md border border-input bg-background pl-8 pr-8 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
	/>
	{#if value}
		<button
			class="absolute right-2 top-2 p-0.5 rounded text-muted-foreground hover:text-foreground"
			onclick={() => {
				value = '';
				onchange?.('');
			}}
			aria-label="Clear search"
		>
			<X class="h-4 w-4" />
		</button>
	{/if}
</div>
